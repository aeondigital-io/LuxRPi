#!/usr/bin/env python3
"""
spinnaker_cam.py — Linux CLI tool for Teledyne/FLIR cameras via PySpin (Spinnaker SDK)

Usage:
  python spinnaker_cam.py <command> [options]

Commands:
  list                          List all connected cameras
  info      [-s SERIAL]         Show camera info and current settings
  get       [-s SERIAL] <setting>  Query a single setting: value + valid range / options
  capture   [-s SERIAL] [options] Capture one or more images
  set       [-s SERIAL] <setting> <value>  Set a camera parameter
  lowpower  [-s SERIAL]         Put camera in low-power mode (stop acquisition + DeInit)
  wakeup    [-s SERIAL]         Wake camera from low-power mode (re-Init)
  reset     [-s SERIAL]         Perform hardware device reset

Run with --help on any sub-command for detailed options.
"""

import argparse
import sys
import os
import time

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

__version__ = "1.1.0"

# ---------------------------------------------------------------------------
# PySpin import guard
# ---------------------------------------------------------------------------
try:
    import PySpin
except ImportError:
    print("ERROR: PySpin not found. Install the Spinnaker SDK and its Python bindings.")
    print("  Download: https://www.flir.com/products/spinnaker-sdk/")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_system():
    return PySpin.System.GetInstance()


def get_camera(cam_list, serial=None):
    """Return the first camera, or the camera matching *serial*."""
    if cam_list.GetSize() == 0:
        raise RuntimeError("No cameras detected.")
    if serial:
        cam = cam_list.GetBySerial(serial)
        if not cam.IsValid():
            raise RuntimeError(f"No camera found with serial '{serial}'.")
        return cam
    return cam_list.GetByIndex(0)


def node_available(node):
    """Return True if a node exists, is readable, and is writable where needed."""
    return node is not None and PySpin.IsAvailable(node)


def node_readable(node):
    return node_available(node) and PySpin.IsReadable(node)


def node_writable(node):
    return node_available(node) and PySpin.IsWritable(node)


def set_enum_node(nodemap, node_name, entry_name):
    """Set an enumeration node by entry symbolic name (case-insensitive match)."""
    node = PySpin.CEnumerationPtr(nodemap.GetNode(node_name))
    if not node_writable(node):
        raise RuntimeError(f"Node '{node_name}' is not writable.")
    # Try exact match first, then fall back to case-insensitive search.
    # GetEntries() returns raw INode objects so each must be cast to
    # IEnumEntry via CEnumEntryPtr before calling GetSymbolic().
    entry = node.GetEntryByName(entry_name)
    if not node_readable(entry):
        entries = node.GetEntries()
        enum_entries = [PySpin.CEnumEntryPtr(e) for e in entries]
        match = next(
            (e for e in enum_entries
             if PySpin.IsAvailable(e) and PySpin.IsReadable(e)
             and e.GetSymbolic().lower() == entry_name.lower()),
            None
        )
        if match is None:
            available = [e.GetSymbolic() for e in enum_entries
                         if PySpin.IsAvailable(e) and PySpin.IsReadable(e)]
            raise RuntimeError(
                f"Enum entry '{entry_name}' not available for '{node_name}'. "
                f"Valid options: {', '.join(available)}"
            )
        entry = match
    node.SetIntValue(entry.GetValue())


def get_enum_node(nodemap, node_name):
    """Get the current symbolic value of an enumeration node."""
    node = PySpin.CEnumerationPtr(nodemap.GetNode(node_name))
    if not node_readable(node):
        return "N/A"
    return node.GetCurrentEntry().GetSymbolic()


def set_float_node(nodemap, node_name, value):
    node = PySpin.CFloatPtr(nodemap.GetNode(node_name))
    if not node_writable(node):
        raise RuntimeError(f"Float node '{node_name}' is not writable.")
    min_v = node.GetMin()
    max_v = node.GetMax()
    if not (min_v <= value <= max_v):
        raise ValueError(f"Value {value} out of range [{min_v}, {max_v}] for '{node_name}'.")
    node.SetValue(value)


def get_float_node(nodemap, node_name, fmt=".2f"):
    node = PySpin.CFloatPtr(nodemap.GetNode(node_name))
    if not node_readable(node):
        return "N/A"
    return f"{node.GetValue():{fmt}}"


def set_int_node(nodemap, node_name, value):
    node = PySpin.CIntegerPtr(nodemap.GetNode(node_name))
    if not node_writable(node):
        raise RuntimeError(f"Integer node '{node_name}' is not writable.")
    min_v = node.GetMin()
    max_v = node.GetMax()
    if not (min_v <= value <= max_v):
        raise ValueError(f"Value {value} out of range [{min_v}, {max_v}] for '{node_name}'.")
    node.SetValue(value)


def get_int_node(nodemap, node_name):
    node = PySpin.CIntegerPtr(nodemap.GetNode(node_name))
    if not node_readable(node):
        return "N/A"
    return str(node.GetValue())


def set_bool_node(nodemap, node_name, value):
    node = PySpin.CBooleanPtr(nodemap.GetNode(node_name))
    if not node_writable(node):
        raise RuntimeError(f"Bool node '{node_name}' is not writable.")
    node.SetValue(bool(value))


def exec_command_node(nodemap, node_name):
    node = PySpin.CCommandPtr(nodemap.GetNode(node_name))
    if not node_writable(node):
        raise RuntimeError(f"Command node '{node_name}' is not executable.")
    node.Execute()


def get_string_node(nodemap, node_name):
    node = PySpin.CStringPtr(nodemap.GetNode(node_name))
    if not node_readable(node):
        return "N/A"
    return node.GetValue()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(args):
    """List all detected cameras."""
    system = get_system()
    cam_list = system.GetCameras()
    count = cam_list.GetSize()
    if count == 0:
        print("No cameras detected.")
    else:
        print(f"Found {count} camera(s):\n")
        for i in range(count):
            cam = cam_list.GetByIndex(i)
            tl_nodemap = cam.GetTLDeviceNodeMap()
            serial  = get_string_node(tl_nodemap, "DeviceSerialNumber")
            model   = get_string_node(tl_nodemap, "DeviceModelName")
            vendor  = get_string_node(tl_nodemap, "DeviceVendorName")
            version = get_string_node(tl_nodemap, "DeviceVersion")
            print(f"  [{i}] Serial: {serial}  Model: {model}  Vendor: {vendor}  FW: {version}")
            del cam
    cam_list.Clear()
    system.ReleaseInstance()


def cmd_info(args):
    """Display current settings of a camera."""
    system = get_system()
    cam_list = system.GetCameras()
    try:
        cam = get_camera(cam_list, args.serial)
        cam.Init()
        nodemap = cam.GetNodeMap()
        tl_nodemap = cam.GetTLDeviceNodeMap()

        serial  = get_string_node(tl_nodemap, "DeviceSerialNumber")
        model   = get_string_node(tl_nodemap, "DeviceModelName")
        vendor  = get_string_node(tl_nodemap, "DeviceVendorName")

        print(f"\n=== Camera: {vendor} {model} (Serial: {serial}) ===\n")
        rows = [
            ("Acquisition Mode",         get_enum_node(nodemap, "AcquisitionMode")),
            ("Pixel Format",             get_enum_node(nodemap, "PixelFormat")),
            ("Width (px)",               get_int_node(nodemap,  "Width")),
            ("Height (px)",              get_int_node(nodemap,  "Height")),
            ("Exposure Mode",            get_enum_node(nodemap, "ExposureMode")),
            ("Exposure Auto",            get_enum_node(nodemap, "ExposureAuto")),
            ("Exposure Time (µs)",       get_float_node(nodemap, "ExposureTime", ".1f")),
            ("Gain (dB)",                get_float_node(nodemap, "Gain")),
            ("Gain Auto",                get_enum_node(nodemap, "GainAuto")),
            ("Gamma Enable",             get_int_node(nodemap,  "GammaEnable") if node_readable(
                                             PySpin.CBooleanPtr(nodemap.GetNode("GammaEnable"))) else "N/A"),
            ("Gamma",                    get_float_node(nodemap, "Gamma")),
            ("Black Level (DN)",         get_float_node(nodemap, "BlackLevel")),
            ("Frame Rate Enable",        get_enum_node(nodemap, "AcquisitionFrameRateEnable")
                                         if PySpin.IsAvailable(nodemap.GetNode("AcquisitionFrameRateEnable"))
                                         else "N/A"),
            ("Frame Rate (fps)",         get_float_node(nodemap, "AcquisitionFrameRate")),
            ("Trigger Mode",             get_enum_node(nodemap, "TriggerMode")),
            ("Trigger Source",           get_enum_node(nodemap, "TriggerSource")),
            ("Balance White Auto",       get_enum_node(nodemap, "BalanceWhiteAuto")),
            ("Device Temperature",       get_enum_node(nodemap, "DeviceTemperature")),
        ]

        col_w = max(len(r[0]) for r in rows) + 2
        for label, val in rows:
            print(f"  {label:<{col_w}}: {val}")
        print()

        cam.DeInit()
    finally:
        del cam
        cam_list.Clear()
        system.ReleaseInstance()


# Shared settings registry - used by both cmd_set and cmd_get
SETTINGS = {
    # key               : (node_name,                   type,    hint / unit)
    "exposure":           ("ExposureTime",               "float", "us  (ExposureAuto must be Off)"),
    "exposure_auto":      ("ExposureAuto",               "enum",  "Off | Once | Continuous"),
    "gain":               ("Gain",                       "float", "dB  (GainAuto must be Off)"),
    "gain_auto":          ("GainAuto",                   "enum",  "Off | Once | Continuous"),
    "gamma":              ("Gamma",                      "float", "0.25 to 4.0"),
    "gamma_enable":       ("GammaEnable",                "bool",  "true | false"),
    "black_level":        ("BlackLevel",                 "float", "digital number"),
    "width":              ("Width",                      "int",   "pixels (multiple of 4 typical)"),
    "height":             ("Height",                     "int",   "pixels (multiple of 4 typical)"),
    "pixel_format":       ("PixelFormat",                "enum",  "e.g. Mono8, BayerRG8, BGR8, RGB8"),
    "acquisition_mode":   ("AcquisitionMode",            "enum",  "Continuous | SingleFrame | MultiFrame"),
    "framerate":          ("AcquisitionFrameRate",       "float", "fps (AcquisitionFrameRateEnable=true needed)"),
    "framerate_enable":   ("AcquisitionFrameRateEnable", "enum",  "true | false (some cameras use bool)"),
    "trigger_mode":       ("TriggerMode",                "enum",  "On | Off"),
    "trigger_source":     ("TriggerSource",              "enum",  "Software | Line0 | Line1 | ..."),
    "balance_white_auto": ("BalanceWhiteAuto",           "enum",  "Off | Once | Continuous"),
    "balance_ratio":      ("BalanceRatio",               "float", "(BalanceRatioSelector must be set first)"),
}


def cmd_get(args):
    """Query the current value and valid range/options of a single setting."""
    setting = args.setting.lower()
    if setting not in SETTINGS:
        print(f"Unknown setting '{setting}'. Available settings:")
        for k, (_, t, hint) in sorted(SETTINGS.items()):
            print(f"  {k:<24} ({t}) -- {hint}")
        sys.exit(1)

    node_name, dtype, hint = SETTINGS[setting]

    system = get_system()
    cam_list = system.GetCameras()
    try:
        cam = get_camera(cam_list, args.serial)
        cam.Init()
        nodemap = cam.GetNodeMap()

        print(f"\n  Setting : {setting}  ({dtype})")
        print(f"  Node    : {node_name}")

        if dtype == "float":
            node = PySpin.CFloatPtr(nodemap.GetNode(node_name))
            if not node_readable(node):
                print("  Status  : not available on this camera")
            else:
                val = node.GetValue()
                mn  = node.GetMin()
                mx  = node.GetMax()
                unit = hint.split()[0] if hint else ""
                print(f"  Value   : {val:.4f}  {unit}")
                print(f"  Min     : {mn:.4f}  {unit}")
                print(f"  Max     : {mx:.4f}  {unit}")
                writable = "yes" if node_writable(node) else "no (read-only or auto active)"
                print(f"  Writable: {writable}")

        elif dtype == "int":
            node = PySpin.CIntegerPtr(nodemap.GetNode(node_name))
            if not node_readable(node):
                print("  Status  : not available on this camera")
            else:
                val  = node.GetValue()
                mn   = node.GetMin()
                mx   = node.GetMax()
                step = node.GetInc()
                print(f"  Value   : {val}")
                print(f"  Min     : {mn}")
                print(f"  Max     : {mx}")
                print(f"  Step    : {step}")
                writable = "yes" if node_writable(node) else "no (read-only)"
                print(f"  Writable: {writable}")

        elif dtype == "bool":
            node = PySpin.CBooleanPtr(nodemap.GetNode(node_name))
            if not node_readable(node):
                print("  Status  : not available on this camera")
            else:
                val = node.GetValue()
                print(f"  Value   : {val}")
                writable = "yes" if node_writable(node) else "no (read-only)"
                print(f"  Writable: {writable}")

        elif dtype == "enum":
            node = PySpin.CEnumerationPtr(nodemap.GetNode(node_name))
            if not node_readable(node):
                print("  Status  : not available on this camera")
            else:
                current = node.GetCurrentEntry().GetSymbolic()
                print(f"  Value   : {current}")
                entries = [PySpin.CEnumEntryPtr(e) for e in node.GetEntries()]
                available = [
                    e.GetSymbolic()
                    for e in entries
                    if PySpin.IsAvailable(e) and PySpin.IsReadable(e)
                ]
                options_str = " | ".join(available)
                print(f"  Options : {options_str}")
                writable = "yes" if node_writable(node) else "no (read-only)"
                print(f"  Writable: {writable}")

        print()
        cam.DeInit()

    except PySpin.SpinnakerException as e:
        print(f"Spinnaker error: {e}")
        sys.exit(1)
    finally:
        del cam
        cam_list.Clear()
        system.ReleaseInstance()


def cmd_set(args):
    """Set a camera parameter."""
    setting = args.setting.lower()
    if setting not in SETTINGS:
        print(f"Unknown setting '{setting}'. Available settings:")
        for k, (_, t, hint) in sorted(SETTINGS.items()):
            print(f"  {k:<24} ({t}) — {hint}")
        sys.exit(1)

    node_name, dtype, hint = SETTINGS[setting]
    raw_value = args.value

    system = get_system()
    cam_list = system.GetCameras()
    try:
        cam = get_camera(cam_list, args.serial)
        cam.Init()
        nodemap = cam.GetNodeMap()

        # Auto-disable guards: turn off the relevant auto mode before writing
        # a manual value, so the node is guaranteed to be writable.
        AUTO_GUARDS = {
            "exposure":    ("ExposureAuto", "Off"),
            "gain":        ("GainAuto",     "Off"),
            "balance_ratio": ("BalanceWhiteAuto", "Off"),
        }
        if setting in AUTO_GUARDS:
            guard_node, guard_value = AUTO_GUARDS[setting]
            try:
                set_enum_node(nodemap, guard_node, guard_value)
                print(f"  {guard_node} -> {guard_value}  (auto-disabled)")
            except Exception as guard_err:
                print(f"  Warning: could not disable {guard_node}: {guard_err}")

        if dtype == "float":
            set_float_node(nodemap, node_name, float(raw_value))
        elif dtype == "int":
            set_int_node(nodemap, node_name, int(raw_value))
        elif dtype == "bool":
            set_bool_node(nodemap, node_name, raw_value.lower() in ("true", "1", "yes"))
        elif dtype == "enum":
            set_enum_node(nodemap, node_name, raw_value)

        print(f"  {setting} -> {raw_value}")
        cam.DeInit()
    except Exception as e:
        print(f"ERROR setting '{setting}': {e}")
        sys.exit(1)
    finally:
        del cam
        cam_list.Clear()
        system.ReleaseInstance()


def cmd_capture(args):
    """Capture one or more images and save to disk."""
    system = get_system()
    cam_list = system.GetCameras()
    try:
        cam = get_camera(cam_list, args.serial)
        cam.Init()
        nodemap = cam.GetNodeMap()

        # Configure acquisition mode
        set_enum_node(nodemap, "AcquisitionMode", "Continuous")

        # Optional per-capture overrides
        if args.exposure is not None:
            set_enum_node(nodemap, "ExposureAuto", "Off")
            set_float_node(nodemap, "ExposureTime", args.exposure)
        if args.gain is not None:
            set_enum_node(nodemap, "GainAuto", "Off")
            set_float_node(nodemap, "Gain", args.gain)
        if args.pixel_format:
            set_enum_node(nodemap, "PixelFormat", args.pixel_format)
        if args.width:
            set_int_node(nodemap, "Width", args.width)
        if args.height:
            set_int_node(nodemap, "Height", args.height)

        processor = PySpin.ImageProcessor()
        processor.SetColorProcessing(
            PySpin.SPINNAKER_COLOR_PROCESSING_ALGORITHM_HQ_LINEAR
        )

        out_fmt_map = {
            "jpg": PySpin.SPINNAKER_IMAGE_FILE_FORMAT_JPEG,
            "jpeg": PySpin.SPINNAKER_IMAGE_FILE_FORMAT_JPEG,
            "png": PySpin.SPINNAKER_IMAGE_FILE_FORMAT_PNG,
            "bmp": PySpin.SPINNAKER_IMAGE_FILE_FORMAT_BMP,
            "tiff": PySpin.SPINNAKER_IMAGE_FILE_FORMAT_TIFF,
            "tif": PySpin.SPINNAKER_IMAGE_FILE_FORMAT_TIFF,
        }
        ext = args.format.lower()
        if ext not in out_fmt_map:
            print(f"ERROR: Unsupported output format '{args.format}'. Use: {', '.join(out_fmt_map)}")
            sys.exit(1)
        out_fmt = out_fmt_map[ext]

        cam.BeginAcquisition()
        print(f"Capturing {args.count} image(s)…")

        saved = []
        for i in range(args.count):
            img = cam.GetNextImage(5000)  # 5-second timeout
            if img.IsIncomplete():
                print(f"  [WARNING] Frame {i} incomplete: {img.GetImageStatus()}")
                img.Release()
                continue

            # Convert to desired output format
            dest_pixel = args.pixel_format or "BGR8"
            try:
                converted = processor.Convert(img, PySpin.PixelFormat_BGR8)
            except Exception:
                converted = img  # use raw if conversion fails

            # Build filename
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            if args.count == 1:
                filename = args.output or f"capture_{timestamp}.{ext}"
            else:
                base = os.path.splitext(args.output)[0] if args.output else f"capture_{timestamp}"
                filename = f"{base}_{i:03d}.{ext}"

            converted.Save(filename, out_fmt)
            w = img.GetWidth()
            h = img.GetHeight()
            print(f"  Saved: {filename}  ({w}×{h})")
            saved.append(filename)

            img.Release()

            if args.count > 1 and args.interval > 0 and i < args.count - 1:
                time.sleep(args.interval)

        cam.EndAcquisition()
        cam.DeInit()
        print(f"\nDone. {len(saved)} image(s) saved.")

    except PySpin.SpinnakerException as e:
        print(f"Spinnaker error: {e}")
        sys.exit(1)
    finally:
        del cam
        cam_list.Clear()
        system.ReleaseInstance()



def cmd_calibrate(args):
    """
    Run a combined autocalibration sequence to find optimal camera settings.

    Sequence
    --------
    1. Exposure + Gain  : run ExposureAuto/GainAuto = Once and wait for convergence.
    2. White Balance    : run BalanceWhiteAuto = Once and wait for convergence
                         (skipped for Mono cameras).
    3. Sharpening       : enable SharpeningAuto if supported.
    4. Analysis         : capture a test frame and report brightness, contrast,
                          and sharpness (Laplacian variance) so you can judge quality.
    5. Lock             : set all auto modes back to Off and print the settled values.

    The final locked values are the optimal manual settings for your current scene.
    Use --no-lock to leave auto modes running instead of locking them.
    """
    import numpy as np

    SETTLE_TIMEOUT = 10.0   # seconds to wait for each auto mode to converge
    SETTLE_POLL    = 0.25   # polling interval in seconds
    WARMUP_FRAMES  = 3      # frames to discard before sampling

    def try_set(nodemap, node_name, value, label=""):
        """Attempt to set a node; warn and continue if unsupported."""
        try:
            set_enum_node(nodemap, node_name, value)
            return True
        except Exception as e:
            tag = label or node_name
            print(f"    [skip] {tag}: {e}")
            return False

    def wait_for_once(nodemap, node_name, label, timeout=SETTLE_TIMEOUT):
        """
        Poll an enum node until it flips from Once back to Off,
        which signals the camera has finished its auto-adjustment pass.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                node = PySpin.CEnumerationPtr(nodemap.GetNode(node_name))
                if node_readable(node):
                    current = node.GetCurrentEntry().GetSymbolic()
                    if current.lower() == "off":
                        return True
            except Exception:
                pass
            time.sleep(SETTLE_POLL)
        print(f"    [warn] {label} did not converge within {timeout:.0f}s — using current value.")
        return False

    def is_mono(nodemap):
        """Return True if the camera is currently in a mono pixel format."""
        try:
            fmt = get_enum_node(nodemap, "PixelFormat").lower()
            return "mono" in fmt or "bayer" not in fmt
        except Exception:
            return False

    def analyse_frame(nodemap, cam):
        """Capture one frame and return (brightness, contrast, sharpness) metrics."""
        try:
            cam.BeginAcquisition()
            # Discard warmup frames
            for _ in range(WARMUP_FRAMES):
                warm = cam.GetNextImage(3000)
                warm.Release()
            img = cam.GetNextImage(5000)
            if img.IsIncomplete():
                img.Release()
                cam.EndAcquisition()
                return None, None, None

            processor = PySpin.ImageProcessor()
            processor.SetColorProcessing(
                PySpin.SPINNAKER_COLOR_PROCESSING_ALGORITHM_HQ_LINEAR
            )
            try:
                mono = processor.Convert(img, PySpin.PixelFormat_Mono8)
                arr = mono.GetNDArray().astype(np.float32)
            except Exception:
                arr = img.GetNDArray().astype(np.float32)
                if arr.ndim == 3:
                    arr = arr.mean(axis=2)

            img.Release()
            cam.EndAcquisition()

            brightness = float(arr.mean())
            contrast   = float(arr.std())
            # Laplacian variance — higher = sharper
            kernel = np.array([[0, 1, 0],[1,-4, 1],[0, 1, 0]], dtype=np.float32)
            from numpy.lib.stride_tricks import sliding_window_view
            h, w = arr.shape
            pad = np.pad(arr, 1, mode="reflect")
            lap = sum(
                kernel[i, j] * pad[i:i+h, j:j+w]
                for i in range(3) for j in range(3)
            )
            sharpness = float(lap.var())
            return brightness, contrast, sharpness

        except Exception as e:
            print(f"    [warn] Frame analysis failed: {e}")
            try:
                cam.EndAcquisition()
            except Exception:
                pass
            return None, None, None

    # ----------------------------------------------------------------
    system = get_system()
    cam_list = system.GetCameras()
    try:
        cam = get_camera(cam_list, args.serial)
        tl_nodemap = cam.GetTLDeviceNodeMap()
        serial = get_string_node(tl_nodemap, "DeviceSerialNumber")
        model  = get_string_node(tl_nodemap, "DeviceModelName")

        cam.Init()
        nodemap = cam.GetNodeMap()

        print(f"\n=== Calibrating: {model} (Serial: {serial}) ===\n")

        # ---- Step 1: Exposure & Gain --------------------------------
        print("  [1/4] Auto Exposure + Gain...")
        set_enum_node(nodemap, "AcquisitionMode", "Continuous")
        cam.BeginAcquisition()
        # Drain a couple of frames so the sensor is live before triggering auto
        for _ in range(2):
            try:
                f = cam.GetNextImage(2000)
                f.Release()
            except Exception:
                pass
        cam.EndAcquisition()

        exp_ok  = try_set(nodemap, "ExposureAuto", "Once", "ExposureAuto")
        gain_ok = try_set(nodemap, "GainAuto",     "Once", "GainAuto")

        if exp_ok or gain_ok:
            # Both auto modes converge together; just wait on ExposureAuto
            wait_node = "ExposureAuto" if exp_ok else "GainAuto"
            wait_for_once(nodemap, wait_node, "Exposure/Gain auto")
        else:
            print("    [skip] Neither ExposureAuto nor GainAuto available on this camera.")

        exposure_us = None
        gain_db     = None
        try:
            exposure_us = PySpin.CFloatPtr(nodemap.GetNode("ExposureTime")).GetValue()
            print(f"    Settled exposure : {exposure_us:.1f} us")
        except Exception:
            pass
        try:
            gain_db = PySpin.CFloatPtr(nodemap.GetNode("Gain")).GetValue()
            print(f"    Settled gain     : {gain_db:.2f} dB")
        except Exception:
            pass

        # ---- Step 2: White Balance ----------------------------------
        wb_red = wb_blue = None
        if not is_mono(nodemap) and not args.skip_wb:
            print("  [2/4] Auto White Balance...")
            wb_ok = try_set(nodemap, "BalanceWhiteAuto", "Once", "BalanceWhiteAuto")
            if wb_ok:
                wait_for_once(nodemap, "BalanceWhiteAuto", "White balance auto")
                try:
                    sel = PySpin.CEnumerationPtr(nodemap.GetNode("BalanceRatioSelector"))
                    ratio = PySpin.CFloatPtr(nodemap.GetNode("BalanceRatio"))
                    for ch in ("Red", "Blue"):
                        try:
                            set_enum_node(nodemap, "BalanceRatioSelector", ch)
                            val = ratio.GetValue()
                            if ch == "Red":
                                wb_red = val
                            else:
                                wb_blue = val
                            print(f"    Settled WB {ch:4s}  : {val:.4f}")
                        except Exception:
                            pass
                except Exception:
                    pass
        else:
            print("  [2/4] White Balance skipped (mono camera or --skip-wb).")

        # ---- Step 3: Sharpening ------------------------------------
        print("  [3/4] Sharpening...")
        sharp_ok = try_set(nodemap, "SharpeningEnable", "true", "SharpeningEnable")
        if sharp_ok:
            auto_sharp = try_set(nodemap, "SharpeningAuto", "On", "SharpeningAuto")
            if not auto_sharp:
                # Fixed sharpening: set a moderate default value
                try:
                    sn = PySpin.CFloatPtr(nodemap.GetNode("Sharpening"))
                    if node_writable(sn):
                        mn, mx = sn.GetMin(), sn.GetMax()
                        moderate = mn + (mx - mn) * 0.35
                        sn.SetValue(moderate)
                        print(f"    Sharpening set to {moderate:.3f} (35% of range)")
                except Exception as e:
                    print(f"    [skip] Could not set Sharpening value: {e}")
        else:
            print("    [skip] Sharpening not supported on this camera.")

        # ---- Step 4: Frame analysis --------------------------------
        print("  [4/4] Analysing test frame...")
        brightness, contrast, sharpness = analyse_frame(nodemap, cam)
        if brightness is not None:
            print(f"    Brightness (mean DN) : {brightness:.1f}  "
                  f"({'ok' if 80 < brightness < 200 else 'consider adjusting scene lighting'})")
            print(f"    Contrast   (std  DN) : {contrast:.1f}")
            print(f"    Sharpness  (Lap var) : {sharpness:.1f}  "
                  f"({'good' if sharpness > 50 else 'low - check focus'})")

        # ---- Step 5: Lock / report ---------------------------------
        if not args.no_lock:
            print("\n  Locking settings (setting auto modes to Off)...")
            for node_name, label in [
                ("ExposureAuto",    "ExposureAuto"),
                ("GainAuto",        "GainAuto"),
                ("BalanceWhiteAuto","BalanceWhiteAuto"),
            ]:
                try:
                    set_enum_node(nodemap, node_name, "Off")
                except Exception:
                    pass  # not all cameras have all nodes

        print("\n=== Calibration complete ===\n")
        print("  Optimal settings found:")
        if exposure_us is not None:
            print(f"    exposure  : {exposure_us:.1f} us")
        if gain_db is not None:
            print(f"    gain      : {gain_db:.2f} dB")
        if wb_red is not None:
            print(f"    WB red    : {wb_red:.4f}")
        if wb_blue is not None:
            print(f"    WB blue   : {wb_blue:.4f}")
        if not args.no_lock:
            print("\n  Auto modes are now OFF — settings are locked to the above values.")
        else:
            print("\n  Auto modes left running (--no-lock). Settings may continue to drift.")
        print()

        cam.DeInit()

    except PySpin.SpinnakerException as e:
        print(f"Spinnaker error: {e}")
        sys.exit(1)
    finally:
        del cam
        cam_list.Clear()
        system.ReleaseInstance()

def cmd_lowpower(args):
    """
    Put camera in low-power / idle state.

    For GigE cameras: disables the heartbeat (prevents GigE link keepalive traffic).
    For all cameras: ends acquisition (if running) and DeInit (releases node map,
    disconnects port).  The camera hardware goes idle until wakeup is called.
    """
    system = get_system()
    cam_list = system.GetCameras()
    try:
        cam = get_camera(cam_list, args.serial)
        tl_nodemap = cam.GetTLDeviceNodeMap()
        serial = get_string_node(tl_nodemap, "DeviceSerialNumber")

        cam.Init()
        nodemap = cam.GetNodeMap()

        # Stop acquisition if running
        try:
            cam.EndAcquisition()
            print("  Acquisition stopped.")
        except PySpin.SpinnakerException:
            pass  # not acquiring — that's fine

        # Disable GigE heartbeat to stop keepalive traffic
        hb_node = PySpin.CEnumerationPtr(nodemap.GetNode("DeviceLinkHeartbeatMode"))
        if node_writable(hb_node):
            try:
                set_enum_node(nodemap, "DeviceLinkHeartbeatMode", "Off")
                print("  GigE heartbeat disabled.")
            except Exception:
                pass  # USB cameras don't have this node

        # DeInit releases the connection and node map
        cam.DeInit()
        print(f"  Camera {serial} is now in low-power / idle mode.")
        print("  Run 'wakeup' to reconnect.")

    finally:
        del cam
        cam_list.Clear()
        system.ReleaseInstance()


def cmd_wakeup(args):
    """Re-initialize a camera from low-power mode."""
    system = get_system()
    cam_list = system.GetCameras()
    try:
        cam = get_camera(cam_list, args.serial)
        tl_nodemap = cam.GetTLDeviceNodeMap()
        serial = get_string_node(tl_nodemap, "DeviceSerialNumber")

        cam.Init()
        nodemap = cam.GetNodeMap()

        # Re-enable heartbeat if it was disabled
        try:
            set_enum_node(nodemap, "DeviceLinkHeartbeatMode", "On")
            print("  GigE heartbeat re-enabled.")
        except Exception:
            pass

        print(f"  Camera {serial} is awake and initialized.")
        cam.DeInit()

    finally:
        del cam
        cam_list.Clear()
        system.ReleaseInstance()


def cmd_reset(args):
    """Perform a hardware device reset."""
    system = get_system()
    cam_list = system.GetCameras()
    try:
        cam = get_camera(cam_list, args.serial)
        tl_nodemap = cam.GetTLDeviceNodeMap()
        serial = get_string_node(tl_nodemap, "DeviceSerialNumber")

        cam.Init()
        nodemap = cam.GetNodeMap()

        print(f"  Resetting camera {serial}…")
        exec_command_node(nodemap, "DeviceReset")
        print("  Reset command sent. Camera will reconnect shortly.")
        # Do NOT call cam.DeInit() after a reset command — the device disappears
    except PySpin.SpinnakerException as e:
        print(f"Spinnaker error during reset: {e}")
    finally:
        cam_list.Clear()
        system.ReleaseInstance()

def cmd_enable_camera_power(args) -> None:
    port = '2-1'
    """Enable power to the camera's USB port"""
    cam_path = f"/sys/bus/usb/devices/{port}/authorized"
    value = "1"
    with open(cam_path, "w") as f:
        f.write(value)

def cmd_disable_camera_power(args) -> None:
    port = '2-1'
    """Disable power to the camera's USB port"""
    cam_path = f"/sys/bus/usb/devices/{port}/authorized"
    value = "0"
    with open(cam_path, "w") as f:
        f.write(value)

# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="spinnaker_cam",
        description=f"CLI tool for Teledyne/FLIR cameras via PySpin (Spinnaker SDK v4.x)  [v{__version__}]",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"spinnaker_cam v{__version__}",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # ---- list ----
    p_list = sub.add_parser("list", help="List connected cameras")
    p_list.set_defaults(func=cmd_list)

    # ---- info ----
    p_info = sub.add_parser("info", help="Show camera info and current settings")
    p_info.add_argument("-s", "--serial", metavar="SERIAL", help="Camera serial number")
    p_info.set_defaults(func=cmd_info)

    # ---- get ----
    p_get = sub.add_parser("get", help="Query a single setting: value + valid range / options")
    p_get.add_argument("-s", "--serial", metavar="SERIAL", help="Camera serial number")
    p_get.add_argument("setting", help="Setting name (use 'set --help' for the full list)")
    p_get.set_defaults(func=cmd_get)

    # ---- capture ----
    p_cap = sub.add_parser("capture", help="Capture image(s)")
    p_cap.add_argument("-s", "--serial",       metavar="SERIAL",  help="Camera serial number")
    p_cap.add_argument("-o", "--output",       metavar="FILE",    help="Output filename (auto if omitted)")
    p_cap.add_argument("-n", "--count",        type=int, default=1, metavar="N", help="Number of frames (default 1)")
    p_cap.add_argument("-i", "--interval",     type=float, default=0.0, metavar="SEC",
                       help="Seconds between frames when -n > 1 (default 0)")
    p_cap.add_argument("-f", "--format",       default="jpg",
                       choices=["jpg","jpeg","png","bmp","tiff","tif"],
                       metavar="FMT", help="Output format: jpg png bmp tiff (default: jpg)")
    p_cap.add_argument("--exposure",           type=float, metavar="US",  help="Exposure time in µs")
    p_cap.add_argument("--gain",               type=float, metavar="DB",  help="Gain in dB")
    p_cap.add_argument("--pixel-format",       metavar="FMT",             help="Pixel format e.g. Mono8, BGR8")
    p_cap.add_argument("--width",              type=int,   metavar="PX",  help="Image width in pixels")
    p_cap.add_argument("--height",             type=int,   metavar="PX",  help="Image height in pixels")
    p_cap.set_defaults(func=cmd_capture)

    # ---- set ----
    p_set = sub.add_parser(
        "set",
        help="Set a camera parameter",
        description="Set a named camera parameter.\n\nAvailable settings:\n"
            "  exposure            float   Exposure time in µs (ExposureAuto must be Off)\n"
            "  exposure_auto       enum    Off | Once | Continuous\n"
            "  gain                float   Gain in dB (GainAuto must be Off)\n"
            "  gain_auto           enum    Off | Once | Continuous\n"
            "  gamma               float   0.25 – 4.0\n"
            "  gamma_enable        bool    true | false\n"
            "  black_level         float   Digital number\n"
            "  width               int     Image width in pixels\n"
            "  height              int     Image height in pixels\n"
            "  pixel_format        enum    Mono8 | BayerRG8 | BGR8 | RGB8 | ...\n"
            "  acquisition_mode    enum    Continuous | SingleFrame | MultiFrame\n"
            "  framerate           float   Frames per second\n"
            "  framerate_enable    enum    true | false\n"
            "  trigger_mode        enum    On | Off\n"
            "  trigger_source      enum    Software | Line0 | Line1 | ...\n"
            "  balance_white_auto  enum    Off | Once | Continuous\n"
            "  balance_ratio       float   (BalanceRatioSelector must be set first)\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_set.add_argument("-s", "--serial", metavar="SERIAL", help="Camera serial number")
    p_set.add_argument("setting", help="Parameter name (see above)")
    p_set.add_argument("value",   help="Value to set")
    p_set.set_defaults(func=cmd_set)

    # ---- calibrate ----
    p_cal = sub.add_parser(
        "calibrate",
        help="Auto-calibrate exposure, gain, white balance, and sharpening",
        description=(
            "Runs a full autocalibration sequence:\n"
            "  1. ExposureAuto + GainAuto = Once  (waits for convergence)\n"
            "  2. BalanceWhiteAuto = Once          (skipped for mono cameras)\n"
            "  3. Enables SharpeningAuto if supported\n"
            "  4. Captures a test frame and reports brightness/contrast/sharpness\n"
            "  5. Locks all auto modes Off and prints the settled values\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_cal.add_argument("-s", "--serial",  metavar="SERIAL", help="Camera serial number")
    p_cal.add_argument("--no-lock",       action="store_true",
                       help="Leave auto modes running after calibration instead of locking")
    p_cal.add_argument("--skip-wb",       action="store_true",
                       help="Skip white balance calibration")
    p_cal.set_defaults(func=cmd_calibrate)

    # ---- lowpower ----
    p_lp = sub.add_parser("lowpower", help="Put camera in low-power / idle mode")
    p_lp.add_argument("-s", "--serial", metavar="SERIAL", help="Camera serial number")
    p_lp.set_defaults(func=cmd_lowpower)

    # ---- wakeup ----
    p_wu = sub.add_parser("wakeup", help="Wake camera from low-power mode")
    p_wu.add_argument("-s", "--serial", metavar="SERIAL", help="Camera serial number")
    p_wu.set_defaults(func=cmd_wakeup)

    # ---- reset ----
    p_rst = sub.add_parser("reset", help="Hardware device reset")
    p_rst.add_argument("-s", "--serial", metavar="SERIAL", help="Camera serial number")
    p_rst.set_defaults(func=cmd_reset)

    # ---- enable-cam ----
    p_enable = sub.add_parser("enable-cam", help="Enable power to camera")
    p_enable.add_argument("-s", "--serial", metavar="SERIAL", help="Camera serial number")
    p_enable.set_defaults(func=cmd_enable_camera_power)

    # ---- disable-cam ----
    p_disable = sub.add_parser("disable-cam", help="Disable power to camera")
    p_disable.add_argument("-s", "--serial", metavar="SERIAL", help="Camera serial number")
    p_disable.set_defaults(func=cmd_disable_camera_power)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        print(f"spinnaker_cam v{__version__}")
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()