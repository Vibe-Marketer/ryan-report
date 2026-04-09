# Catom App -- How to Run Your Ryan Report

This guide walks you through installing and using the Catom app to generate your Ryan report.

---

## What You Need Before Starting

- A Mac computer
- Your Axon login info:
  - Company subdomain (example: `catom`)
  - Username
  - Password
- Your current Ryan moves CSV file (example: `2026 RYAN MOVES.csv`)

---

## Step 1: Install the App

1. You will receive the installer file:
   - **Mac**: `Catom.pkg` -- double-click it and follow the prompts. It installs Catom into your Applications folder automatically.
   - **Windows**: `Catom.exe` -- double-click it and follow the prompts.
2. Open **Catom** from your Applications folder (Mac) or Start Menu (Windows).

---

## Step 2: First-Time Setup

When you open Catom for the first time, a setup wizard will walk you through everything.

### Pick Your Browser

The app will show which browsers it found on your computer (Chrome, Comet, or Chromium).

- **Comet** is the easiest option -- no extra verification steps.
- **Chrome** works great but requires a one-time verification code the first time (see below).

### Enter Your Axon Credentials

- **Subdomain** -- just the short name, not the full web address. Example: `catom` (the app builds the full address for you).
- **Username** -- your Axon login username.
- **Password** -- your Axon login password.

### Choose Your Historical Ryan Moves File

Click Browse and select your existing Ryan Moves file. This can be either a **.xlsx** or **.csv** file (for example, `2026 RYAN MOVES.xlsx`).

Important: This must be your **original Ryan Moves file** -- the one you have been maintaining with all previous moves. Do NOT select one of the downloaded Axon reports. If you are starting fresh and do not have one yet, skip this step and the app will create one for you.

---

## Step 3: Chrome Two-Factor Verification (One Time Only)

If you chose **Chrome** as your browser, the first time the app connects it will need a verification code. This is a security step from Google, not from the Catom app.

1. The app will open Chrome in the background to set up a dedicated profile.
2. A popup will appear asking for a **verification code**.
3. Check your phone or email for the code (it comes from Google, sent to the account owner).
4. Enter the code in the popup and click OK.
5. After this first time, Chrome remembers your verification -- you will not be asked again.

If you chose **Comet**, skip this step entirely. No verification needed.

---

## Step 4: Run Your Report

From the main screen you have three buttons:

| Button | What It Does |
|---|---|
| **Run All** | Downloads reports from Axon, then builds your Ryan report. This is what you will use most of the time. |
| **Download Only** | Just downloads the source reports from Axon without building anything. |
| **Build Only** | Builds the Ryan report from files already downloaded. Use this if you already have the source files. |

### What Happens When You Click Run All

1. The app opens your browser in the background -- you will not see it and it will not interrupt your work.
2. It logs into Axon and downloads three reports: New RYAN, Order Master Report, and audit info.
3. It builds your updated Ryan report from the downloaded data.
4. The streaming log on screen shows you what is happening in real time.
5. When finished, the app cleans up the source files automatically.

### Where to Find Your Output

After a successful run, you will find two files in your download folder:

- **generated-ryan-report-latest-new-only.csv** -- only the new moves since your last report.
- **append-ryan-report-latest.csv** -- the full updated report with everything appended.

---

## Step 5: Change Settings (If Needed)

Click the **Settings** tab to update any of the following:

- Browser selection
- Axon credentials (subdomain, username, password)
- Download folder location
- Historical Ryan CSV file
- Schedule (for automatic runs)
- Airtable push settings
- Which reports to pull

Always save your changes before running.

---

## Troubleshooting

### The app will not open

Go to **System Settings > Privacy & Security** and click **Open Anyway** next to the Catom message.

### Login fails

- Double-check your subdomain, username, and password in Settings.
- Make sure the subdomain is just the short name (example: `catom`), not the full web address.

### The browser opens but nothing happens

- Try switching to a different browser in Settings.
- If using Chrome, you may need to redo the verification code step.

### The report downloads but the build fails

- Make sure your historical Ryan CSV file is selected correctly in Settings.
- Make sure the file has not been moved or renamed.

### I need more help

Click the **Get Help** button in the app. This sends your logs to an AI assistant that will analyze the problem and give you specific troubleshooting steps. (Requires an Anthropic API key in Settings.)

---

## How Often to Run

Run the report whenever you need updated Ryan moves. Typical schedule:

- Weekly
- End of billing cycle
- Whenever Ryan requests updated data

