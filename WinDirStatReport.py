# -*- coding: utf-8 -*-
# WinDirStatReport.py - Autopsy (Jython) report module
# Builds a sparse "ghost" copy of a data source's file tree and opens it in WinDirStat.
#
# Install: <Autopsy python_modules>\WinDirStatReport\WinDirStatReport.py
# (Tools -> Python Plugins opens the folder), then restart Autopsy.

import os
import re
import time
import subprocess
import traceback
import jarray

from java.lang import Throwable
from java.nio import ByteBuffer
from java.nio.file import Files, Paths, StandardOpenOption, OpenOption
from java.nio.file.attribute import FileTime

from org.sleuthkit.autopsy.casemodule import Case
from org.sleuthkit.autopsy.report import GeneralReportModuleAdapter
from org.sleuthkit.autopsy.report import ReportProgressPanel

# ---------------- Configuration ----------------
WINDIRSTAT_EXE = os.environ.get("WINDIRSTAT_EXE",
                                r"C:\Program Files (x86)\WinDirStat\windirstat.exe")
# Short, local, NON-OneDrive folder for the ghost tree. Falls back to the report folder.
GHOST_BASE = os.environ.get("WDS_GHOST_BASE", r"C:\wds_ghost")
USE_LONG_PATHS = True       # use \\?\ prefix so paths >260 chars work (WinDirStat 2.x needed to view them)
INCLUDE_DELETED = True      # include unallocated (deleted) files
LAUNCH_WINDIRSTAT = True
CHUNK_SIZE = 20000          # rows fetched per DB query
MAX_COMPONENT_LEN = 80
# -----------------------------------------------

MAX_PATH_LEN = 30000 if USE_LONG_PATHS else 240

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = set(["CON", "PRN", "AUX", "NUL"] +
                ["COM%d" % i for i in range(1, 10)] +
                ["LPT%d" % i for i in range(1, 10)])


def clean_component(name):
    name = _INVALID.sub("_", name).rstrip(" .")
    if not name:
        name = "_"
    if name.split(".")[0].upper() in _RESERVED:
        name = "_" + name
    if len(name) > MAX_COMPONENT_LEN:
        base, ext = os.path.splitext(name)
        name = base[:MAX_COMPONENT_LEN - len(ext)] + ext[:MAX_COMPONENT_LEN // 2]
    return name


def jpath(path):
    """Java Path, using the \\\\?\\ long-path prefix when needed."""
    if USE_LONG_PATHS and len(path) > 240 and not path.startswith("\\\\?\\"):
        path = "\\\\?\\" + os.path.abspath(path)
    return Paths.get(path)


def is_file(path):
    return Files.isRegularFile(jpath(path))


def is_dir(path):
    return Files.isDirectory(jpath(path))


def ensure_dir(root, parts):
    """Create nested folders one component at a time.
    If a component already exists as a FILE, use '<name>_dir' instead."""
    cur = root
    for c in parts:
        nxt = os.path.join(cur, c)
        if is_file(nxt):
            nxt = os.path.join(cur, c + "_dir")
        if not is_dir(nxt):
            try:
                Files.createDirectory(jpath(nxt))
            except Throwable:
                if not is_dir(nxt):   # tolerate races, re-raise real failures
                    raise
        cur = nxt
    return cur


def create_sparse_file(path, size, mtime):
    """Create a sparse file of logical length `size` (no data blocks allocated)."""
    p = jpath(path)
    opts = jarray.array([StandardOpenOption.CREATE_NEW,
                         StandardOpenOption.WRITE,
                         StandardOpenOption.SPARSE], OpenOption)
    ch = Files.newByteChannel(p, opts)
    try:
        if size > 0:
            ch.position(size - 1)
            ch.write(ByteBuffer.wrap(jarray.zeros(1, 'b')))
    finally:
        ch.close()
    if mtime and mtime > 0:
        try:
            Files.setLastModifiedTime(p, FileTime.fromMillis(long(mtime) * 1000))
        except Throwable:
            pass


def choose_ghost_root(base_dir, case_name):
    """Prefer a short local folder; fall back to the report directory."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    short = clean_component(case_name)[:20]
    try:
        root = os.path.join(GHOST_BASE, "%s_%s" % (short, stamp))
        Files.createDirectories(Paths.get(root))
        return root
    except Throwable:
        root = os.path.join(base_dir, "ghost_tree")
        Files.createDirectories(Paths.get(root))
        return root


class WinDirStatReportModule(GeneralReportModuleAdapter):
    moduleName = "WinDirStat Treemap"

    def getName(self):
        return self.moduleName

    def getDescription(self):
        return ("Builds a sparse mirror of each data source's file tree and "
                "opens it in WinDirStat for a visual size/type overview.")

    def getRelativeFilePath(self):
        return "windirstat_summary.txt"

    def generateReport(self, reportSettings, progressBar):
        # Autopsy versions differ: newer pass a settings object, older pass a path string.
        if hasattr(reportSettings, "getReportDirectoryPath"):
            base_dir = reportSettings.getReportDirectoryPath()
        else:
            base_dir = reportSettings

        progressBar.setIndeterminate(True)
        progressBar.start()
        progressBar.updateStatusLabel("Querying case database...")

        summary_path = os.path.join(base_dir, self.getRelativeFilePath())
        created = skipped = failed = 0
        first_failure = None

        try:
            case = Case.getCurrentCase()
            sk = case.getSleuthkitCase()
            ghost_root = choose_ghost_root(base_dir, case.getName())

            for ds in sk.getDataSources():
                ds_id = ds.getId()
                ds_dir = ensure_dir(ghost_root, [clean_component(ds.getName())])
                progressBar.updateStatusLabel("Mirroring " + ds.getName())

                last_obj = 0
                while True:
                    where = ("data_source_obj_id = %d AND meta_type = 1 AND obj_id > %d"
                             % (ds_id, last_obj))
                    if not INCLUDE_DELETED:
                        where += " AND dir_type = 1"
                    where += " ORDER BY obj_id LIMIT %d" % CHUNK_SIZE

                    batch = sk.findAllFilesWhere(where)
                    if batch.isEmpty():
                        break

                    for f in batch:
                        last_obj = max(last_obj, f.getId())
                        try:
                            parts = [clean_component(c)
                                     for c in f.getParentPath().split("/") if c]
                            fname = clean_component(f.getName())

                            if (len(ds_dir) + sum(len(p) + 1 for p in parts)
                                    + len(fname) + 1 > MAX_PATH_LEN):
                                skipped += 1
                                continue

                            folder = ensure_dir(ds_dir, parts)
                            target = os.path.join(folder, fname)
                            try:
                                create_sparse_file(target, f.getSize(), f.getMtime())
                            except Throwable:
                                # Name collision (e.g. a folder already has this name)
                                base, ext = os.path.splitext(fname)
                                alt = os.path.join(folder, "%s~%d%s" % (base, f.getId(), ext))
                                create_sparse_file(alt, f.getSize(), f.getMtime())
                            created += 1
                        except (Throwable, Exception) as fe:
                            failed += 1
                            if first_failure is None:
                                first_failure = "%s%s: %s" % (f.getParentPath(), f.getName(), fe)

                    progressBar.updateStatusLabel(
                        "Mirroring %s: %d files so far" % (ds.getName(), created))

            with open(summary_path, "w") as out:
                out.write("WinDirStat ghost tree\n=====================\n")
                out.write("Location : %s\n" % ghost_root)
                out.write("Created  : %d files\n" % created)
                out.write("Skipped  : %d (path too long)\n" % skipped)
                out.write("Failed   : %d\n" % failed)
                if first_failure:
                    out.write("First failure: %s\n" % first_failure)
                out.write("Deleted files included: %s\n" % INCLUDE_DELETED)
                out.write("Long paths (\\\\?\\) enabled: %s\n" % USE_LONG_PATHS)
                out.write("\nNote: files are sparse placeholders; sizes/dates/names "
                          "mirror the evidence, content does not.\n")

            case.addReport(summary_path, self.moduleName, "WinDirStat ghost tree summary")

            if LAUNCH_WINDIRSTAT:
                if os.path.exists(WINDIRSTAT_EXE):
                    subprocess.Popen([WINDIRSTAT_EXE, ghost_root])
                else:
                    progressBar.updateStatusLabel(
                        "WinDirStat not found at: " + WINDIRSTAT_EXE)

            progressBar.complete(ReportProgressPanel.ReportStatus.COMPLETE)

        except (Throwable, Exception) as e:
            progressBar.updateStatusLabel("Error: " + str(e))
            try:
                with open(os.path.join(base_dir, "windirstat_error.txt"), "w") as out:
                    out.write(traceback.format_exc() + "\n" + str(e))
            except Exception:
                pass
            progressBar.complete(ReportProgressPanel.ReportStatus.ERROR)
