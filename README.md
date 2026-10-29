# Jobnesty alerts

GitHub Actions logs in to the Jobnesty dashboard every 15 minutes, and when a job's
resume is ready (`completed`) and hasn't been seen before, it sends one push to your
phone through [ntfy](https://ntfy.sh). Jobs already alerted on are stored in `seen.json`,
which the workflow commits back to the repo.

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
- **Schedule:** cron is UTC and GitHub often starts scheduled runs a few minutes late.
  Edit the `cron:` line in `.github/workflows/check.yml` to change the window.
- **Actions minutes:** private repos get 2,000 free minutes a month, and each run is
  billed rounded up to the whole minute. The default schedule is 48 runs a day, and a run
  (installing Chromium plus a possible Render cold start) likely takes 1.5-3 minutes, so
  it may go over the free 2,000 minutes a month. Check Settings → Billing after a few days, and narrow the cron
  window, e.g. `*/15 13-17 * * *` (20 runs/day), once you know when jobs land.
