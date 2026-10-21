"""Locations and tunables. The tunables are defaults: a profile can change them (see profile.py)."""
import importlib.util
import os

DEFAULT_ROOT = os.path.expanduser("~/Data/rosbags")
CACHE_DIR = os.path.expanduser("~/.cache/bag-catalog")
HAVE_ROS = importlib.util.find_spec("rosbag2_py") is not None

# --- Defaults for the settings a profile can change (profile.py) ----------------------------

# Sensor grouping: which topics belong to which sensor column.
CAMERA_TYPES = {
    "sensor_msgs/msg/CompressedImage", "sensor_msgs/msg/Image", "sensor_msgs/msg/CameraInfo",
    "ffmpeg_image_transport_msgs/msg/FFMPEGPacket", "theora_image_transport/msg/Packet",
}
POINTCLOUD_TYPES = {"sensor_msgs/msg/PointCloud2", "sensor_msgs/msg/LaserScan"}
# trailing topic name parts dropped to get a sensor's name: /camera/image_raw/compressed -> camera
CAMERA_SUFFIXES = {"image_raw", "image", "image_rect", "image_color", "compressed", "compressedDepth",
                   "raw", "color", "camera_info", "ffmpeg", "theora"}
POINTCLOUD_SUFFIXES = {"points", "cloud_registered", "cloud", "scan", "points_raw"}
IGNORED_SEGMENTS = {"camera_driver", "driver"}  # /stereo/driver/left/image -> stereo/left
SENSOR_ALIASES = {"tf_static": "tf"}
SENSOR_RULES = {
    "camera_types": CAMERA_TYPES, "pointcloud_types": POINTCLOUD_TYPES,
    "camera_suffixes": CAMERA_SUFFIXES, "pointcloud_suffixes": POINTCLOUD_SUFFIXES,
    "ignored_segments": IGNORED_SEGMENTS, "aliases": SENSOR_ALIASES,
}

# Message types for routes (GNSS preferred, else dead-reckoned odometry) and camera frames.
GNSS_TYPES = {"sensor_msgs/msg/NavSatFix"}
ODOM_TYPES = {"nav_msgs/msg/Odometry", "geometry_msgs/msg/TwistWithCovarianceStamped",
              "geometry_msgs/msg/TwistStamped"}
IMAGE_TYPES = {"sensor_msgs/msg/CompressedImage", "sensor_msgs/msg/Image"}

# Bags whose name contains this get a "merged" tag (e.g. made with `ros2 bag convert`).
MERGED_MARKER = "merged"

# Thumbnail source, in order of preference (sensor names as shown in the column headers).
# Also changeable in the app, under Cameras on the Camera card.
THUMB_SENSORS = ["front_camera", "camera"]
THUMB_OFFSET_S = 1.0  # take the first frame this far in, to skip auto-exposure warm-up

# Gaps: a pause between two messages of a topic longer than both GAP_FACTOR x its usual (median)
# interval and GAP_MIN_S. Both are adjustable in the app, down to the floors below.
GAP_FACTOR, GAP_MIN_S = 3.0, 0.2
GAP_FACTOR_FLOOR, GAP_MIN_S_FLOOR = 1.5, 0.05

TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_ATTRIBUTION = "© OpenStreetMap"
USER_AGENT = "bag-catalog/1.0 (personal rosbag browser)"
