# Qanopy — Multi-Interface CAN Analyzer

**Visualizer, Trace & Logger (PyQt / Windows x64)**

Qanopy is a Windows 64-bit CAN bus analyzer built with **PyQt (MDI UI)**. It combines real-time signal plotting, multi-DBC decoding, a CANalyzer-style Trace window, and timestamped logging. It is designed for engineers who need a clean, extensible toolchain around DBC-driven workflows.

> **Performance Note:** Qanopy is built to stay responsive under load using multi-threaded RX/TX workers. It supports multiple CAN interfaces simultaneously via `python-can` (Vector, IXXAT, PCAN, gs_usb, slcan, etc.).

---

## ⚡ Why Qanopy Exists

Most teams struggle with a fragmented workflow using a mix of vendor tools (CANalyzer, PCAN-View) and ad-hoc Python scripts for decoding. Qanopy consolidates these into one application that is:

* **DBC-Centric:** Nodes → Messages → Signals hierarchy.
* **Multi-Interface:** Run several buses in parallel.
* **Multi-DBC per Interface:** Associate multiple DBCs to one bus without overwriting.
* **Plot-First:** Double-click signals to visualize immediately.
* **Trace-First:** See every frame live, expand to see decoded signals.
* **Automation-Ready:** Supports periodic TX, filters, logging, and modular code.

---

## 🛠 Key Features

### 🔌 Multi-Interface CAN Sessions
Create and run multiple independent CAN sessions simultaneously. Each session maps to a specific CAN adapter + channel (e.g., `Vector:0`, `IXXAT:1`) and maintains its own:
* RX Pipeline & TX Scheduler
* Trace Buffer
* Filters & Logging Pipeline
* **Supported Backends:** Vector, IXXAT, PCAN, gs_usb / slcan, SocketCAN (Linux).

### 📂 Multiple DBCs per Session
Unlike tools that restrict you to one DBC, Qanopy supports **multiple DBC files** attached to a single session. They appear as independent namespaces in the tree:
`Session` → `DBC Filename` → `Node` → `Message` → `Signal`

* **Use Case:** Separate DBCs for different domains (BMS, VCU, Cluster) or overlaying multiple protocols.
* **Collision Safety:**
    * Rejects duplicate filenames to prevent silent collisions.
    * Deterministic routing (first loaded wins) if two DBCs define the same Frame ID (with warning).

### 🌲 DBC Browser Tree
Navigate an expandable hierarchy of **Nodes**, **Messages** (Frame ID visible), and **Signals**. Double-click any signal to instantly add it to the plot window.

### 📈 Real-Time Graphing
High-performance plotting using `pyqtgraph`.
* **Stacked Signals:** Add multiple signals; graphs stack vertically.
* **High Contrast:** Automatically assigns dark, distinct colors (no washed-out pastels).
* **Navigation:** Zoom-in/out, Zoom-to-fit, Axis scaling.
* **Cursors:** Measurement and Delta cursors with snap resolution.
* **Differential Analysis:** Select two signals to merge them into a derived plot (e.g., `A - B`) for sensor plausibility checks.

### 📝 Trace Window
A dedicated MDI view showing "bus truth"—all incoming frames regardless of decoding filters.
* **Columns:** Time, SOF, Δt (per ID), Channel, ID, Name, Direction, DLC, Data.
* **Expandable Rows:** Click to reveal decoded signals (Physical values, Units, Raw values).

### 📡 Transmit Window
Full transmit workflow handling both Raw and DBC-based frames.
* **Modes:** One-shot or Periodic (ms).
* **Raw:** Support for Extended IDs (29-bit).
* **DBC:** Select Message → Enter Signal Values → Encode & Send.
* **Threading:** Periodic TX jobs run in a dedicated thread to ensure UI responsiveness.

### 🔍 Filter Window
Dedicated filtering per **Session** and per **DBC**.
* **Modes:** Include (allow only selected) or Exclude (block selected).
* **Scope:** Apply filters to decoded signals/plots and optionally toggle for logging.

### 💾 Timestamped Logging
* Log CAN traffic to files for offline analysis.
* Filter-aware logging options.
* Extensible architecture (ready for MDF/ASC/BLF implementation).

---

## 🏗 Architecture Overview

Qanopy is structured for maintainability and extension.

* **`CanSession`:** Manages one CAN interface/channel. Owns the RX thread, TX worker, Trace buffer, and Logger.
* **`MultiDbcManager`:** Loads multiple DBCs, routes `Frame ID → Active DBC Key`, and detects collisions.
* **`CanRxThread`:** Receives frames from `python-can`, pushes to Trace (unfiltered), applies filters, decodes signals, and updates the DataStore.
* **`CanTxWorker`:** Handles one-shot sends and periodic scheduling without blocking the UI.
* **`DataStore`:** Time-series store for plotted signals (Keyed by `session:dbc:id:signal`).
* **`UI (MDI)`:** Central area managing Plot, Trace, Filter, Transmit, and Log windows.

---

## 📦 Requirements & Installation

Qanopy relies on standard Python libraries for engineering and GUI work:

* **Python 3.x**
* `PyQt6`
* `pyqtgraph`
* `python-can`
* `cantools`
* `numpy`

```bash
# Example installation
pip install PyQt6 pyqtgraph python-can cantools numpy

## License & Attribution

This project is licensed under the **Apache License 2.0**. 

If you use this software in a commercial product or a research project, 
attribution is required under the terms of the license. Please credit as:

> **Qanopy** by [Rishi Franklin] (https://github.com/rishifranklin)