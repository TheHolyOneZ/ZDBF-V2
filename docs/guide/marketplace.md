# ZSync Marketplace

The [ZSync Marketplace](https://zsync.eu/extension/) is a catalogue of community extensions for
ZDBF. You browse, check and install them from Discord, without touching files.

- [Browse](#browse)
- [Activate your key](#activate-your-key)
- [Install](#install)
- [The safety scan](#the-safety-scan)
- [Python packages](#python-packages)
- [Updates and removal](#updates-and-removal)
- [Settings](#settings)

## Browse

| Command | Who | Does |
|---|---|---|
| `/marketplace` | Everyone | Browse the catalogue (aliases `!mp`, `!mkt`) |
| `/marketplace search <query>` | Everyone | Search the catalogue |
| `/marketplace info <extension>` | Everyone | Details of one extension |
| `/marketplace updates` | Everyone | Installed extensions with a newer version |

The marketplace license is shown the first time someone uses it and is accepted once per user.

## Activate your key

Every installation has a **ZSync ZDBF Key**. Downloads need the key to be activated once:

1. Run `/marketplace key` (bot owner) to see the key. It is stored in `data/marketplace/`.
2. Fill in the form at [zsync.eu/extension/activate.php](https://zsync.eu/extension/activate.php).
3. Confirm the link in the email you get.
4. A second email arrives once the key is approved.

A key migrated from V1 keeps its activation. Questions about keys go to the ZSync Discord, linked
from `/marketplace key`.

## Install

`/marketplace install <extension>` (bot owner) downloads the extension and shows the safety scan
before anything is written. Then choose:

- **Install and load**: installs the Python packages it still needs, saves the file to
  `extensions/` and loads it right away.
- **Install only** (or **Install file only** when packages are missing): saves the file. Load it
  later with the **Load now** button or `/ext load <name>`.
- **Cancel**.

If a file with the same name already exists, the scan says so: installing overwrites it. A file
the scan cannot read is blocked from installing.

Installed extensions behave like any other extension: they hot-reload, show up in `/ext list` and
`/plugins`, and can be managed from the dashboard.

## The safety scan

The scan reads the code without running it and lists:

- every module it imports,
- risky modules: `subprocess`, `ctypes`, `socket`, `shutil`, `pickle`, `marshal`,
- risky calls such as `eval`, `exec`, `os.system`, `Popen`, file deletion,
- whether it has a `setup` function (the entry point every extension needs),
- the Python packages that are not installed yet.

A risky item is not proof of bad intent. A music extension needs `subprocess` for FFmpeg, for
example. It is a reason to read the code, or to ask the author, before installing.

## Python packages

Many extensions need extra packages (`aiohttp` add-ons, image libraries, APIs). The bot works out
which ones are missing:

- Imports inside `try: ... except ImportError:` count as optional and are not installed.
- **Install and load** runs `pip` (or `uv pip` when pip is missing) in the bot's own Python
  environment, then loads the extension. Only the bot owner can do this.
- `/marketplace fixdeps` installs the missing packages of extensions that failed to load.
- `requirements-extensions.txt` lists packages that popular extensions use, to install ahead of time.

Set `[marketplace] auto_install_packages = false` to only list the packages, never install them.

## Updates and removal

| Command | Does |
|---|---|
| `/marketplace updates` | Compares installed versions with the catalogue |
| `/marketplace install <extension>` | Installs the newer version over the old one |
| `/marketplace uninstall <name>` | Unloads the extension and deletes its file |
| `/marketplace refresh` | Reloads the catalogue now instead of waiting for the cache |

## Settings

`[marketplace]` in `config.toml`:

| Key | Default | Meaning |
|---|---|---|
| `api_url` | the ZSync catalogue | Where the list comes from |
| `download_url` | the ZSync download endpoint | Where files come from |
| `cache_minutes` | `10` | How long the catalogue is cached |
| `auto_install_packages` | `true` | Offer to install missing packages and load in one step |

The marketplace tab on the **Extensions** page of the [web dashboard](dashboard.md) does the same:
check a file (imports, entry point, missing packages, the code itself), then install it. Installing
from the website needs the `marketplace` capability and the bot owner's approval by default.

Publishing your own extension: see [docs/dev/extensions.md](../dev/extensions.md#publishing-on-the-marketplace).
