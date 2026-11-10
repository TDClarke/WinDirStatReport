# WinDirStatReport

An [Autopsy](https://www.autopsy.com/) report module (Jython) that builds a sparse "ghost" copy of a data source's file tree and opens it in [WinDirStat](https://windirstat.net/), so you get an instant visual overview of what is on the evidence by size and file type.

The ghost tree mirrors the **names, folder structure, sizes and modified dates** of the files in your case. It does not contain any of the evidence content. Every file is a sparse placeholder that reports the correct logical size but allocates no data blocks on disk, so even very large data sources take up almost no space.

## Features

- Adds a **WinDirStat Treemap** option to Autopsy's report generator
- Mirrors every data source in the current case into its own top-level folder
- Creates sparse files (NTFS) with the original size and last-modified time
- Optionally includes deleted (unallocated) files
- Handles long paths via the `\\?\` prefix, and skips anything that still cannot fit
- Sanitises names that Windows would reject (invalid characters, reserved names such as `CON`/`NUL`, trailing dots and spaces, overlong components)
- Resolves name collisions instead of failing
- Launches WinDirStat on the ghost tree automatically when finished
- Writes a summary of what was created, skipped and failed, and attaches it to the case as a report

## Requirements

- Windows
- Autopsy 4.x or later (with Jython python-module support)
- [WinDirStat](https://windirstat.net/). Version 2.x is recommended, since it is needed to view paths longer than 260 characters.
- An **NTFS** volume for the ghost tree, because sparse files are required to keep it small

## Installation

1. In Autopsy, open **Tools → Python Plugins**. This opens the `python_modules` folder.
2. Create a folder named `WinDirStatReport` inside it and copy `WinDirStatReport.py` into it:

   ```
   <Autopsy python_modules>\WinDirStatReport\WinDirStatReport.py
   ```

3. Restart Autopsy.

## Usage

1. Open your case in Autopsy and let ingest finish (or at least let the file system be added).
2. Go to **Generate Report** and select **WinDirStat Treemap**.
3. Click through the wizard. The module runs, builds the ghost tree and launches WinDirStat on it.
4. Explore the treemap, extension list and directory tree as usual.

A summary file, `windirstat_summary.txt`, is saved in the report folder and listed under **Reports** in the case.

## Configuration

Settings are constants at the top of `WinDirStatReport.py`. Two can also be set through environment variables.

| Setting | Default | Description |
|---------|---------|-------------|
| `WINDIRSTAT_EXE` (env var) | `C:\Program Files (x86)\WinDirStat\windirstat.exe` | Path to the WinDirStat executable. Override this if yours is installed elsewhere. |
| `WDS_GHOST_BASE` (env var) | `C:\wds_ghost` | Base folder for the ghost tree. Use a short, local, non-OneDrive path on NTFS. Falls back to `ghost_tree` inside the report folder if it cannot be created. |
| `USE_LONG_PATHS` | `True` | Use the `\\?\` prefix so paths over 260 characters work. |
| `INCLUDE_DELETED` | `True` | Include deleted/unallocated files. |
| `LAUNCH_WINDIRSTAT` | `True` | Open WinDirStat when the report finishes. |
| `CHUNK_SIZE` | `20000` | Number of rows fetched per database query. |
| `MAX_COMPONENT_LEN` | `80` | Maximum length of any single file or folder name. Longer names are truncated, keeping the extension. |

## Output

Each run creates a new timestamped folder:

```
C:\wds_ghost\<CaseName>_<YYYYMMDD_HHMMSS>\
└── <Data source name>\
    └── ...mirrored folders and sparse files...
```

Report-folder files:

- `windirstat_summary.txt`: ghost tree location, counts of files created, skipped (path too long) and failed, the first failure message, and the settings used
- `windirstat_error.txt`: only written if the module hits a fatal error, and contains the traceback

## Notes and limitations

- **Placeholders only.** File content is not copied. Do not use the ghost tree as a copy of the evidence.
- **Regular files only.** Folders are created implicitly from file paths, so empty folders do not appear.
- **Renamed items.** Names are sanitised to be valid on Windows, so some may differ slightly from the originals. If a file name collides with an existing name, it is saved as `<name>~<objectId><ext>`. If a folder name collides with a file, it is saved as `<name>_dir`.
- **Paths that are too long** are skipped and counted in the summary.
- **Cleanup is manual.** The ghost tree is not deleted automatically, so remove it from `WDS_GHOST_BASE` when you are done.
- **Handle with care.** The ghost tree still exposes file names, paths and dates from your case, which can be sensitive, so store it accordingly.
- The `\\?\` prefix is only added for paths longer than 240 characters.

## How it works

1. Reads the data sources from the case's Sleuth Kit database.
2. Queries regular files (`meta_type = 1`) in batches, optionally restricted to allocated files only.
3. For each file, rebuilds the parent path, sanitises each component, and creates the folders.
4. Creates a sparse file by seeking to `size - 1`, writing a single byte, and setting the modified time.
5. Writes the summary, attaches it to the case, and launches WinDirStat on the ghost root.

## Troubleshooting

- **WinDirStat does not open.** The status label will show `WinDirStat not found at: ...`. Set the `WINDIRSTAT_EXE` environment variable to the correct path, or open the ghost folder (see `windirstat_summary.txt`) in WinDirStat manually.
- **Many files "Failed" or "Skipped".** Check the `First failure` line in the summary. Use a shorter `WDS_GHOST_BASE`, make sure it is on NTFS, and leave `USE_LONG_PATHS` on.
- **Report option not listed.** Confirm the folder and file names match the path in the Installation section, then restart Autopsy.

## Acknowledgements

- [Autopsy](https://www.autopsy.com/) and [The Sleuth Kit](https://www.sleuthkit.org/) for the forensic platform and database API
- [WinDirStat](https://github.com/windirstat/windirstat) for the visualisation

## License

Add a license here (e.g. MIT or GPL-3.0) and include a matching `LICENSE` file in the repository.
License: GNU 2.0
