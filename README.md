# Jobnesty alerts

On weekdays at 7:00 AM Eastern, GitHub Actions logs in to the Jobnesty dashboard once
and reloads it every 2 minutes until 8:30. When a job's resume is ready (`completed`)
and hasn't been seen before, it sends one push to your phone through
[ntfy](https://ntfy.sh) and stops checking for the rest of that day. Jobs already alerted on are stored in `seen.json`,
and the date of the last alert in `last_alert.txt`; the workflow commits both back to the repo.

## One-time setup

1. **Pick an ntfy topic.** Anyone who knows the topic name can read your alerts, so make
   it long and random, e.g. `python3 -c "import secrets; print('jn-' + secrets.token_hex(12))"`.
2. **Phone:** install the ntfy app, tap **+**, and subscribe to that topic on the default
   server (ntfy.sh). Allow notifications when iOS asks.
3. **Repo:** create a **private** GitHub repo and push this folder to it:
   ```sh
   git init && git add . && git commit -m "Jobnesty alerts"
   git branch -M main
   git remote add origin git@github.com:<you>/jobnesty-alerts.git
   git push -u origin main
   ```
4. **Secrets:** in the repo, go to Settings → Secrets and variables → Actions → New
   repository secret, and add `JN_EMAIL`, `JN_PASSWORD` and `NTFY_TOPIC`.

## Testing

1. Actions tab → **Check Jobnesty** → **Run workflow**. The first run records the
   current jobs in `seen.json` and sends **no** alert. Check that the log says
   `First run: recorded N jobs` and that a "Update seen.json" commit appears.
2. Edit `seen.json` on GitHub and delete one `"resume:…"` line (keep the JSON valid).
3. Run the workflow again. Your phone should buzz with that one job.

### Running locally

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && playwright install chromium
printf 'JN_EMAIL=...\nJN_PASSWORD=...\nNTFY_TOPIC=...\n' > .env   # gitignored
python check.py --dry-run          # real login, prints parsed rows, no alert, no seen.json write
python check.py --fixture tests/fixture_dashboard.html --dry-run   # offline parser check
```

Rows marked `NEW` in the dry-run output are the ones that would trigger an alert.

## Troubleshooting

- **"Still on /login after submitting"**: wrong credentials, or the login selectors at
  the top of `check.py` don't match the page. Record the real ones with
  `playwright codegen https://jobnesty-kikk.onrender.com/login` and update
  `EMAIL_SELECTOR`, `PASSWORD_SELECTOR` and `SUBMIT_SELECTOR`.
- **"No job rows found"** or **"Timed out twice"**: the site was down, or the dashboard
  markup changed. Run `python check.py --dry-run` locally to see what it parses.
  GitHub emails you when a run fails, so you'll hear about breakage.
- **"Dashboard looks paginated" warning**: only the first page is checked. Dedup does
  not depend on sort order, but a new job that lands beyond page 1 would be missed.
- **No push but the log says "Sent alert"**: check the topic in the app matches the
  `NTFY_TOPIC` secret exactly, and that iOS notifications are enabled for ntfy.
- **Want alerts before the resume is ready?** Set `READY_STATUS = None` in `check.py`.
- **Schedule:** GitHub can't schedule more often than every 5 minutes, so the 2-minute
  checks happen inside one long run (`check.py --watch`). Cron is UTC and ignores daylight
  saving, so the workflow fires at :00 and :30 over 11:00-13:30 UTC on weekdays and its
  "Gate" step skips starts outside 7:00-8:30 Eastern (or after today's alert). The extra
  starts are backups in case GitHub drops or delays the 7:00 one; while a run is watching
  they wait in the queue (or show as cancelled) and then skip at the gate.
  To change the window, edit the `cron:` line, the times in the gate step, and
  `WATCH_UNTIL` / `WATCH_INTERVAL_S` in `check.py`.
- **Resumes that finish after the alert:** checking stops after the first alert of the
  day, so jobs whose resumes complete later that morning won't push. They'll still be
  on the dashboard, and they'll be included in the next day's alert as "new".
- **Manual runs** (Run workflow button) ignore the time window and the once-a-day stop.
- **Actions minutes:** the watching run is billed for the whole time it's open: about
  65 minutes on a day the alert comes at ~8:05, and 90 on a day with no alert. Over
  ~22 weekdays that's roughly 1,400-2,000 of the free 2,000 minutes a month for private
  repos. If you run out, runs stop until the next month (no charge unless you've added
  a payment method and spending limit). To save minutes, start later (e.g. 7:30) or
  make the repo public, which has unlimited free minutes; secrets stay hidden, but
  `seen.json` and run logs become visible.
- **Test the watch loop locally:** `python check.py --watch --dry-run --interval 20 --until 23:59`
  (Ctrl+C to stop).
