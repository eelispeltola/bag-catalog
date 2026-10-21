# Bag Catalog

Fully vibe-coded, use at your own peril!

A desktop browser for rosbag2 recordings. It shows what each recording contains (which cameras,
lidars and other sensors have data), when it was recorded, how long it is, how far the vehicle
drove, the route on a map and a camera frame.

Bags are grouped into recordings by the folder they are in, so a recording split into several
bags shows as one row that you can expand (see [Folder structure](#folder-structure)).

## Running

Requirements: system Python with PySide6 (≥ 6.7, including QtSvg), PyYAML and numpy; lz4 and
zstandard to read image resolutions from compressed MCAP files; ROS 2 for routes and camera 
frames.

```
./install.sh              # symlinks bag-catalog into ~/.local/bin and adds an app-menu entry
bag-catalog [FOLDER ...]  # up to 3 folders; default: the folders open last time, else ~/Data/rosbags
```

Up to three bag folders can be open at once; their recordings are merged into one list. The list 
is remembered in `~/.config/bag-catalog/bag-catalog.conf`; folders given on the command line are
used for that session only. A folder that isn't there (an unplugged drive) is shown in red and
skipped.

See `bag-catalog --help` for CLI options. `--print-profile` prints all settings in effect as
a commented profile file (see below).

The table opens instantly because it's built from `metadata.yaml` alone. Routes, distances and
thumbnails are extracted in the background with `rosbag2_py`. The launcher sources
`/opt/ros/*/setup.bash` itself when ROS isn't already sourced. Results are cached in
`~/.cache/bag-catalog`, and map tiles come from OpenStreetMap.

To uninstall: `rm ~/.local/bin/bag-catalog ~/.local/share/applications/bag-catalog.desktop
~/.local/share/icons/hicolor/scalable/apps/bag-catalog.svg`.

## Folder structure

The catalog assumes one folder per recording, holding that recording's bags. Above that, folders
can be organised any way you like, to any depth:

```
~/Data/rosbags/                              an opened folder
├── bag_catalog.yaml                         optional: settings shared by everyone who opens it
├── 2610/1006/                               any folders for organising, e.g. by date or vehicle
│   ├── 16_34/                               a recording: the folder its bags are in
│   │   ├── bag_notes.yaml                   its notes and favorite star (written by the app)
│   │   ├── rosbag2_2026_10_06-16_34_38-1/   a bag
│   │   │   ├── metadata.yaml
│   │   │   └── rosbag2_2026_10_06-16_34_38-1_0.mcap
│   │   ├── rosbag2_2026_10_06-16_34_38-2/
│   │   └── rosbag2_2026_10_06-16_34_54-1/   bags from another recorder, in the same recording
│   └── 16_45/
└── rosbag2_2026_10_07-09_12_03/             a bag directly in an opened folder
```

- **A bag** is a folder with a `metadata.yaml`, or `.mcap` / `.db3` files. The catalog doesn't look
  inside a bag for more bags. A bag without `metadata.yaml` is still listed, with an error, and
  `ros2 bag reindex` can rebuild the file (see [Repairing a bag](#repairing-a-bag)).
- **A recording** is the folder its bags are in. Every bag in that folder belongs to it: bags split
  by size or time, bags from several recorders running side by side, and merged copies. The
  recording is named by its path below the opened folder, e.g. `2610/1006/16_34`.
- **A bag directly in an opened folder** has no recording folder, so it is listed as its own
  recording, and its `bag_notes.yaml` goes inside the bag folder.
- **Anything else** is ignored: folders without bags, and other files next to the bags. Extra files
  inside a bag folder are shown as tags on the bag, but don't count towards its size.
- **Opened folders:** up to three, scanned completely. A bag reachable from two of them (one
  inside the other) is listed once. Symbolic links to folders inside an opened folder are not
  followed, but you can open a folder through a link.
- **Bag files** are never changed. The app writes only `bag_notes.yaml`, and `bag_catalog.yaml` if
  you save one there from Settings.

## Notes and favorites

Notes and favorites belong to recordings. Star one with the ☆ in front of its name, with
**Favorite** in the Recording notes panel, or with Ctrl+D. Select a recording, or any of its 
bags, to type notes in the panel. Notes save automatically, show as a yellow tag on the 
recording row, and are covered by search.

Both are stored in the recording folder, under the name `bag_notes.yaml`:

```yaml
# Recording notes from bag-catalog. Plain YAML: fine to read or edit by hand.
favorite: true
notes: |-
  Sunny, dry gravel road.
  Front camera slightly overexposed at the start.
updated: '2026-10-21T18:52:19'
```

A bag lying directly in an opened folder counts as its own recording, so its file goes in the bag
folder instead. The notes travel with the recording when you copy it, and other tools can read
them: `grep -rl --include=bag_notes.yaml 'favorite: true' ~/Data/rosbags` lists the favorites.
Keys added by other tools are kept, and the file is removed when a recording has neither a star
nor notes. The bags themselves are never touched. Editing in a read-only folder shows an error
instead of saving. Changes made to the files elsewhere show up after a rescan (F5).

## Using it

- **Sensor columns:** a filled dot means recorded, a half dot means some of the sensor's topics
  are empty, and a ring means the topics exist but have no messages. The coloured bar under each
  header marks the kind (camera / lidar / other).
- **Click a sensor header** to show only recordings that have that sensor. Within them, only bags
  with any of the selected sensors are listed.
- **Timeline:** grey shows when a recording has bags; orange shows where each bag sits in it.
- **Distance:** from GNSS fixes, or dead-reckoned from twist/odometry if there's no GNSS
  (shown with ≈).
- **Topic details** (Topics panel): typical rate (from the median interval between messages; the
  average is in the tooltip), image resolution, and gaps (count · longest; hover for when they
  happen). These come from the MCAP files' own index, so nothing is decoded. All bags are
  analysed once in the background (about 1–2 minutes for 300 GB) and cached.
- **Gaps** are pauses longer than both a multiple of the topic's usual interval (default 3×) and a
  minimum (default 0.2 s). Change both under **Gaps** in the filter bar; this is applied instantly.
  A topic that stops early or starts late counts as a gap at the bag's end or start. Bags with gaps
  get an amber tag, and the affected sensor dots get an amber ring.
- **Not finalized** (red tag): the recorder stopped before writing the MCAP index. Data may be
  missing at the end; the Messages column shows how many messages are really in the file. ROS often
  can't open such a file, and then shows no route or camera frame. See
  [Repairing a bag](#repairing-a-bag).
- **Merged** (orange tag): a bag whose name contains `merged`, or one found to hold the messages
  of other bags in the same folder (its time span covers them and the message counts add up, topic
  by topic). Its tooltip names those bags.
- **Camera frame:** taken about a second into the recording, from the first camera that has images
  in the list under **Cameras** (on the Camera card). Check, uncheck and reorder cameras there.
  Frames already extracted for a camera are cached, so switching back is instant.
- **Columns** (in the filter bar, or right-click any column header) shows or hides columns,
  including individual sensor columns. The choice is remembered.
- **Expand all / Collapse all** open or close every recording (Ctrl+Shift+Down / Ctrl+Shift+Up).
- Double-click opens the folder, Ctrl+C copies bag paths, and right-click copies a
  `ros2 bag play` command. Ctrl+F searches, F5 rescans.

## Settings and profiles

**Settings** (the sliders button in the title bar, or Ctrl+,) has a page for each group of settings:

- **Sensor columns:** how topics become sensor columns. Which message types count as cameras and
  lidars, which trailing topic name parts are dropped (`/camera/image_raw/compressed` →
  `camera`), name parts ignored everywhere (`driver`), and renames (`stereo/left: left_camera`).
- **Camera frame:** the camera order, the image message types, and how far in the frame is taken.
- **Routes:** the GNSS and odometry message types the route and distance come from. Custom types
  work if they have the same fields (`latitude`, `longitude`, `status.status`; or a `twist`).
- **Gaps** and **Map** (tile URL and attribution, for another tile server).
- **Appearance:** light, dark or follow the desktop. This is personal and never part of a profile.

These settings (all but Appearance) are kept in plain YAML *profile* files, read in layers where
each one overrides single settings of the ones before:

1. the built-in defaults
2. `bag_catalog.yaml` in an open folder, or the nearest folder above it. Put one at the top of a
   shared bag folder and everyone who opens it gets the same sensor grouping. With several open
   folders, the first folder's file wins.
3. `~/.config/bag-catalog/profile.yaml`, your own. Settings, **Cameras** and **Gaps** write it,
   keeping only what differs from the layers below, so a setting you never changed follows the
   folder's file. **Reset** next to a setting goes back to the folder's or the built-in value.

You can also edit the files by hand (Settings › Profile files › Open in text editor); changes apply
on the next rescan (F5). Comments in your own file are not kept when the app rewrites it. Unknown or
invalid settings are skipped and reported in the status bar and the terminal.

To share settings, use **Export to file…** on the same page: it writes the settings that differ
from the built-in defaults to a YAML file. Saved as `bag_catalog.yaml` at the top of a bag folder,
it becomes that folder's profile. **Import from file…** fills the pages from such a file: only the
settings in it change, and nothing is applied until you press Save. `bag-catalog --print-profile`
prints every setting in effect, and [examples/bag_catalog.yaml](examples/bag_catalog.yaml) is a
commented example. A profile looks like this:

```yaml
# bag_catalog.yaml: only the settings that differ from the defaults are needed
sensors:
  ignored_segments: [driver, sensing]
  aliases: {stereo/left: left_camera, stereo/right: right_camera}
thumbnails:
  cameras: [left_camera, rear_camera]
routes:
  gnss_types: [sensor_msgs/msg/NavSatFix, my_msgs/msg/GnssFix]
```

## Files it reads and writes

Everything the catalog knows about your bags lives in plain files, most of them YAML that you can
read, edit and share:

| File | Where | What |
|---|---|---|
| `metadata.yaml` | each bag folder | Written by rosbag2 (`ros2 bag reindex` rebuilds it). The catalog reads it to build the table, and never changes it. |
| `bag_notes.yaml` | each recording folder | Your notes and favorite star for that recording (see [Notes and favorites](#notes-and-favorites)). |
| `bag_catalog.yaml` | a bag folder, or one above it | A shared profile for everyone who opens that folder (see [Settings and profiles](#settings-and-profiles)). [examples/bag_catalog.yaml](examples/bag_catalog.yaml) is a commented example. |
| `profile.yaml` | `~/.config/bag-catalog/` | Your own settings: only the ones you changed. Written by the Settings page. |
| `bag-catalog.conf` | `~/.config/bag-catalog/` | Not YAML: the open folders, hidden columns and colour scheme, kept by Qt. |
| cache | `~/.cache/bag-catalog/` | Topic statistics, routes, camera frames and map tiles. Safe to delete; it is rebuilt. |

## Repairing a bag

A bag whose recorder was stopped abruptly is **not finalized**: its MCAP file has no index at the end,
and its `metadata.yaml` may list more messages than the file holds. To repair one:

1. Write a repaired copy of the MCAP file with the [mcap CLI](https://mcap.dev/guides/cli). The
   original is left untouched:
   ```
   mcap recover <bag folder>/<name>_0.mcap -o repaired.mcap
   ```
2. Move the original out of the bag folder as a backup, and put the repaired file in its place
   under the original name. Keep the backup outside the bag folder: the next step reads the bag's
   files from there.
3. Rebuild `metadata.yaml` from the repaired file, so the message counts and duration match it.
   This overwrites the existing `metadata.yaml`; copy it first if you want to keep it:
   ```
   ros2 bag reindex <bag folder>
   ```
4. Rescan (F5).

Step 3 on its own also helps when only `metadata.yaml` is wrong or missing, e.g. when the Messages
column shows fewer messages in a finalized file than `metadata.yaml` lists. `ros2 bag reindex`
doesn't repair the MCAP file itself, so for a bag that isn't finalized it needs steps 1–2 first.

## Development

```
python3 -m bag_catalog [FOLDER ...]   # run from the checkout (with PYTHONPATH=src), or use bin/bag-catalog
python3 -m pytest                     # tests
```

The code in `src/bag_catalog/` is in three layers, and each only uses the ones below it:

- **Core, without Qt or ROS:** finding bags and grouping them into recordings and sensors from
  `metadata.yaml` (`model.py`), notes (`notes.py`), and settings: built-in defaults in `config.py`,
  profile files and their layering in `profile.py`. This is where most behaviour is decided, and
  where most tests are.
- **Background work:** the slow parts run in worker processes, so the window never waits for them.
  `extract.py` holds the jobs. Topic statistics and gaps come from the MCAP files' own index
  (`mcap_index.py`, no ROS needed); routes and camera frames are decoded with `rosbag2_py`. The jobs
  must not import Qt, because the workers are spawned fresh.
- **Interface, PySide6 (`ui/`):** `window.py` builds the main window from widgets that each look
  after one part of it (the recordings table, the detail cards, the menus, the Settings page) and
  wires them together with Qt signals. `ui/jobs.py` queues the background work, caches the results
  and announces each one. Colours come from `theme.py`; custom-painted widgets read
  `theme.current` when they paint, so switching between light and dark only needs a repaint.

Conventions:

- **Defaults** for anything someone might want to change live in `config.py`. A setting that
  should be changeable per robot or team also goes in `profile.py` (`DEFAULTS` and its help text) and
  gets a label on the Settings page (`ui/settings.py`); the page builds its editor from the
  default's type.
- **Personal state** that shouldn't be shared (open folders, hidden columns, colour scheme) goes
  through `prefs.py` instead.
- **Files are written atomically** with `files.atomic_write`, so a crash never leaves half a file,
  and caches that can't be read are rebuilt.
- **Tests** cover the core and the background jobs directly; anything that can be decided without
  a window should be, so it can be tested.
