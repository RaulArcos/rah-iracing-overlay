# **RAH iRacing Overlay**

**iRacing Input Telemetry Overlay** is an open-source Python-based project that provides real-time telemetry from iRacing, displaying input data both through a web interface so you can put it on programs like OBS or screen overlay for using it on your game.

I just didn't wanted to pay for some overlays subcriptions to have the overlay that I actually wanted, so why not trying? I hope you feel the same, this is free of course ;)

<p align="center">
  <img src=https://github.com/RaulArcos/rah-iracing-overlay/blob/development/images/input-telemetry.gif>
  <img src=https://github.com/RaulArcos/rah-iracing-overlay/blob/development/images/interface.png  width="600">
</p>

## **Table of Contents**

- [Compilation](#compilation)
- [Usage](#usage)
- [Available overlays](#available-overlays)
- [Contributing](#contributing)
- [License](#license)

## **Compilation**

You can compile your own modified version, or make use of the precompiled one you can find on releases of this repo.

### **Prerequisites**

Before compiling, make sure you have the following installed:

- **Python 3.10+**: Ensure you have Python installed. You can download it from [here](https://www.python.org/downloads/).
- **iRacing SDK**: Install iRacing for telemetry data [here](https://github.com/kutu/pyirsdk.git).
- **Requirements file**: You will find a requirements.txt file on the repo for you to get all the libraries.
  
### **1. Clone the Repository**

```bash
git clone https://github.com/RaulArcos/rah-iracing-overlay.git
cd iracing-input-telemetry-overlay
```

### **2. Install Dependencies**

```bash
pip install -r requirements.txt
```

### **3. Compile into an EXE file**

```bash
python3.10.exe (or your version) build_exe.py
```

## **Usage**

Just open the .exe file like a normal windows program, you will be welcomed by an easy interace to open any of the overlays, as well as modify its position or opening it on their web version to get the link for OBS.

<p align="center">
  <img src=https://github.com/RaulArcos/rah-iracing-overlay/blob/development/images/interface_with_movement.png  width="600">
</p>

## Windows Security: DLL blocking after download (Mark-of-the-Web)

Some Windows downloads add a security mark (`Zone.Identifier`) to extracted binaries. This may block runtime DLL loading (`Python.Runtime.dll`, WebView DLLs).

Current releases include a startup safeguard that removes this mark from bundled runtime binaries before the telemetry stack initializes.

If a user still hits this issue, run this once inside the extracted release folder:

```powershell
Get-ChildItem -Recurse -File | Unblock-File
```

For maintainers: the robust long-term solution for public releases is code signing (Authenticode/Trusted Signing).

## **Available overlays**

Every overlay is discovered automatically by the launcher and can be opened as `http://127.0.0.1:8085/overlay/<name>` (add `?theme=glass` for the Glass style; Original is the default).

| Overlay | Folder / route name | Purpose |
|---------|---------------------|---------|
| Input Telemetry | `input_telemetry` | Throttle, brake, clutch, steering and gear |
| Relative | `relative` | Nearby cars and estimated gaps |
| Radar | `radar` | Close-proximity car alerts |
| BlindSpot | `blindspot` | Left/right blindspot warnings |
| Track Map | `track_map` | Cars on a lap-progress ring |
| Laptime graph | `laptime_graph` | Lap-time trend, best/last/delta |
| Fuel & Finish | `fuel_finish` | Fuel, observed burn per clean lap, advisory finish estimate ([details](docs/fuel-session.md)) |
| Session Strip | `session_strip` | Session type, laps/time remaining, state, flag and position ([details](docs/fuel-session.md)) |
| Battle & Pace | `battle_pace` | Same-class car ahead/behind, race gap, last/best lap comparison and observed lap trend ([details](docs/battle-standings.md)) |
| Multiclass Standings | `standings` | Overall and class rank per class group with laps, best/last lap, pit flag and race gaps ([details](docs/battle-standings.md)) |
| Pit Assistant | `pit_assistant` | Read-only pit status, pit speed limit margin when the track reports one, repair/tow timers and requested service ([details](docs/pit-weather.md)) |
| Weather | `weather` | Observed air/track temperature, humidity, wind, precipitation and track wetness; not a forecast ([details](docs/pit-weather.md)) |

## **Contributing**

I hope you want to take part on this journey! Everyone is welcome to add diferent overlays to show interesting data like stadings positions, predicted points... you name it! These are the steps you should do to make this posible:

Remember!! You will find another README file on /src/overlays with steps to implement new overlays as easy as posible!

1. Fork the project.
2. Clone your forked repository to your local machine.
3. Create a new branch for your feature or fix:
 ```bash
git checkout -b feature-name
```
4. Commit your changes
```bash
git commit -m "Add some feature"
```
5. Pust your changes!
```bash
git push origin feature-name
```

## **License**
This project is licensed under the MIT License.
