# Installation Guide

## System Requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.11 | 3.12 |
| RAM | 512 MB | 1 GB |
| Disk | 100 MB | 500 MB |
| OS | Windows 10 / Ubuntu 20.04 / macOS 12 | Windows 11 / Ubuntu 22.04 |
| Browser | Chrome 114+ | Latest Chrome |

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/yourname/DeliveryZoneApp.git
cd DeliveryZoneApp
```

---

## Step 2 — Create a Virtual Environment

**Windows (PowerShell)**:
```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

**Windows (Command Prompt)**:
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

**macOS / Linux**:
```bash
python3 -m venv venv
source venv/bin/activate
```

You should see `(venv)` prepended to your terminal prompt.

---

## Step 3 — Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

This installs:
- Flask, Werkzeug (web framework)
- Pandas, openpyxl (data parsing)
- openai (Gemini-compatible client)
- Selenium, webdriver-manager (browser automation)
- pytesseract, Pillow (OCR — optional)
- python-dotenv (environment variables)

---

## Step 4 — Install Tesseract OCR (Optional)

Only needed if you plan to upload image files (JPG/PNG).

**Windows**:
1. Download from: https://github.com/UB-Mannheim/tesseract/wiki
2. Run the installer
3. Note the installation path (default: `C:\Program Files\Tesseract-OCR\`)
4. Add `TESSERACT_PATH` to your `.env` file:
   ```
   TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
   ```

**Ubuntu / Debian**:
```bash
sudo apt-get update
sudo apt-get install tesseract-ocr
```

**macOS**:
```bash
brew install tesseract
```

---

## Step 5 — Configure Environment Variables

```bash
# Windows
copy .env.example .env

# macOS/Linux
cp .env.example .env
```

Edit `.env` and fill in your values:

```env
GEMINI_API_KEY=your_gemini_api_key_here
TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### Getting a Gemini API Key

1. Visit [https://aistudio.google.com/](https://aistudio.google.com/)
2. Sign in with your Google account
3. Click **Get API Key** → **Create API key in new project**
4. Copy the key (starts with `AIza...`)
5. Paste it in your `.env` file

---

## Step 6 — Install Google Chrome

Selenium requires Chrome to be installed. webdriver-manager automatically downloads the matching ChromeDriver.

- **Windows**: [Download Chrome](https://www.google.com/chrome/)
- **Ubuntu**: `sudo apt-get install google-chrome-stable`
- **macOS**: [Download Chrome](https://www.google.com/chrome/)

---

## Step 7 — Verify Setup

```bash
# Check Python version
python --version  # Should be 3.11+

# Check all packages installed
pip list | grep -E "Flask|pandas|openai|selenium"

# Run the application
python app.py
```

Expected output:
```
INFO:root:Area mapping cached: 9 city entries
 * Running on http://0.0.0.0:5000
 * Debug mode: on
```

Open your browser at [http://localhost:5000](http://localhost:5000).

---

## Upgrading

```bash
git pull origin main
pip install -r requirements.txt --upgrade
```

---

## Uninstalling

```bash
deactivate
cd ..
rm -rf DeliveryZoneApp
```
