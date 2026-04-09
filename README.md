# ATISQUE — Ground Station UI (Tkinter)

This project is a **desktop UI** for a ground station that will receive telemetry (via a LoRa module over UART/Serial) and display it in a dashboard.

Right now the repository contains the **UI shell** (tabs + styling) and a **serial telemetry logger script** (`ground.py`). The UI wiring to live telemetry will be added later.

## Requirements

- Python **3.13+**
- [`uv`](https://docs.astral.sh/uv/) installed

## Install dependencies (uv)

From the project folder:

```bash
uv sync
```

If you’re missing packages:

```bash
uv add pillow matplotlib pyserial
uv sync
```

## Run the UI

```bash
uv run python main.py
```

## Run the serial telemetry logger

```bash
uv run python ground.py
```

### macOS: choose the correct serial port

If you see an error like:

`could not open port /dev/cu.usbserial-0001: No such file or directory`

it means the configured port **doesn’t exist** on your machine. List available ports:

```bash
ls /dev/cu.*
```

Then set `PORT` inside `ground.py` to one of the ports that actually appears (common examples: `/dev/cu.usbmodem*`, `/dev/cu.SLAB_USBtoUART`, `/dev/cu.wchusbserial*`).

## Project structure

- `main.py`: App entrypoint (Tkinter window + tabs)
- `ui_estilos.py`: Theme, colors, and header/logo rendering
- `tab_analisis.py`: Telemetry dashboard layout + Matplotlib figure (currently placeholder values)
- `tab_monitor.py`: Serial monitor tab UI (widgets only; connection logic to be added)
- `tab_imagenes.py`: Image viewer tab UI (placeholders)
- `tab_config.py`: Config tab UI (placeholders)
- `ground.py`: Standalone script to read UART/serial and save telemetry (work in progress)

