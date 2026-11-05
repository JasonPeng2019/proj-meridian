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

The submission report and accompanying screenshots are in [report/](report/).

## Setup

You need **[uv](https://docs.astral.sh/uv/getting-started/installation/)**.
The launcher downloads Python 3.12 automatically if needed, then installs the
locked runtime dependencies. First launch needs internet; later browsing works
offline. Chat needs internet and your own OpenAI or Anthropic API key.

The delivery includes the prepared JSON catalog, all 30 drawings and page images,
parts-list data, AI receipts, review decisions, nine reconstructed parts with 12
GLB/STEP variants, recovery caches, and the built frontend. Reconstructions retain
explicit omissions where evidence or supported templates are incomplete. Source,
tests and verification reports are also included. You do not need Node, a database
server, CAD tools or prep agents. Startup reads the supplied data without rerunning
preparation or CAD. Credentials and personal chat history are excluded.

**1. Download the app.**

```sh
git clone --branch v1 https://github.com/JasonPeng2019/proj-meridian.git
cd proj-meridian
```

For a ready-to-deliver copy, download the app ZIP from
[Releases](https://github.com/JasonPeng2019/proj-meridian/releases), extract it,
and open a terminal in its `Meridian` folder, alongside this README. Git is not
required for the ZIP. Install uv first if `uv --version` is unavailable, then
reopen your terminal.

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

## Saved data and troubleshooting

The prepared catalog lives in `generated/`, append-only reviews in `decisions/`,
and saved chats in `.runtime/chats/`. Data survive app restarts. Back them up
before replacing an installation;
do not overwrite your own decisions when unpacking a new release. Extract into
a fresh folder to try a new release independently.

If port 8001 is busy, stop the other app. For uv, an alternative is
`start.bat --port 8002` or `sh ./start.sh --port 8002`. If chat is disabled,
check the key in `.env` and restart. Provider access to the configured model is
required. Browsing remains available without credentials.

The release includes `SHA256SUMS` for its downloads and a
`DELIVERY-MANIFEST.json` inside the app ZIP with hashes of every packaged file.
No platform-specific `.venv` is shipped: uv creates the right environment for
your operating system. No Docker installation is needed.
