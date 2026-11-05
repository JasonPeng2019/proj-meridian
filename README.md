# Meridian

Meridian lets you ask questions about the supplied OpenLPBF project and inspect
its parts, engineering drawings, source evidence, and available 3D reconstructions.

## Features

- Chat using your own OpenAI or Anthropic API key, with clickable sources and attached parts.
- Search parts by name, section, material, and available views.
- View original drawings with zoom, multiple sheets, and highlighted source regions.
- Orbit available 3D reconstructions, compare alternative readings, and download STEP files.
- Reopen saved chats. Use optional **Debug** for evidence, model checks, review
  queues, corrections, and decision history.

## Setup

You need **uv and Python 3.12**. Use Git to clone, or download the repository ZIP.
Prepared records, drawings, 3D files, and
the built frontend are included. You do not need Node, a database server, CAD
tools, or prep agents. First launch needs internet access to install Python
dependencies. Chat also needs internet access and an OpenAI or Anthropic API key.

**1. Download the app.**

```sh
git clone --branch v1 https://github.com/JasonPeng2019/proj-meridian.git
cd proj-meridian
```

You can also download and extract the repository ZIP, then open a terminal in
that folder.

**2. Add your API key.** Copy `.env.example` to `.env` in the project folder.
Set one key in `.env`:

```dotenv
OPENAI_API_KEY=your_api_key_here
```

Or, for Anthropic:

```dotenv
ANTHROPIC_API_KEY=your_api_key_here
```

OpenAI uses **GPT-6-luna**. Anthropic defaults to **Claude Sonnet 5.5**.
If both keys are set, OpenAI is used unless you add `CHAT_PROVIDER=anthropic`.

`.env` is ignored by Git. Do not commit your key. Skip this step to browse parts,
drawings, and models without chat.

**3. Start the app.**

Windows PowerShell:

```powershell
.\start.bat
```

Linux or macOS:

```sh
sh ./start.sh
```

**4. Open [http://127.0.0.1:8001](http://127.0.0.1:8001).**

The launcher installs dependencies on first use and loads the prepared data.
It serves the included Embedder-style interface without a frontend build or a
separate preview download. Keep the terminal open; press **Ctrl+C** to stop.

To show the engineering Debug view, start with `--debug-ui`:

```powershell
.\start.bat --debug-ui
```

On Linux/macOS, use `sh ./start.sh --debug-ui`. Then open
[Debug](http://127.0.0.1:8001/review/parts). Normal launches hide Debug.

Chats and new review decisions are stored locally. 3D reconstructions are limited
to geometry supported by the supplied evidence.
