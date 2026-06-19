# cns2zss

A Python script that converts M.U.G.E.N CNS character state files to Ikemen GO ZSS format.

## What this tool does

- Mechanical syntax conversion.
- Converts CNS triggers to ZSS `if` blocks.
- Converts state controller formatting.
- Merges consecutive controllers with identical triggers under the same block.
- Removes sections unrelated to character states (`[Data]`, `[Command]`, etc).
- Handles duplicate state definitions and controller parameters, which would crash in ZSS.
- Respects original code execution order.
- Respects `persistent` and `ignoreHitPause` flags.
- Preserves original comments.

## What this tool does not do

- Optimize code to take full advantage of ZSS features (loops, etc).
- Check if triggers, state controller and parameter names are valid.
- Combine opposite triggers into `if`/`else` blocks. They are rare in CNS and would substantially increase the script's complexity.
- Convert `:=` assignment syntax. It will convert most of the block, but also warn the user because such blocks require manual adjustment.

## Usage

### Command Line (core script)

```bash
python cns2zss.py input.cns [output.zss]
```

If no output file is given, the result is saved as `input.cns.zss` in the same folder.

### GUI (graphical front-end)

```bash
python cns2zss_gui.py
```

Launches a GUI for the script.  

## Example

**Input (CNS)**

```
[Statedef 1026]
type    = A
moveType= H
physics = N

[State 1026, Velocity]
type = HitVelSet
trigger1 = Time = 0
x = 1
y = 1

[State 1026, Gravity]
type = VelAdd
trigger1 = 1
y = .45

[State 1026, No scroll]
type = ScreenBound
triggerall = Pos y < -15
trigger1 = BackEdgeBodyDist < 65
trigger2 = FrontEdgeBodyDist < 65
value = 1
movecamera = 0,1

[State 1026, Hit wall]
type = ChangeState
triggerall = Pos y < -15
trigger1 = BackEdgeBodyDist <= 20
trigger2 = FrontEdgeBodyDist <= 20
value = 1027

[State 1026, Hit ground]
type = SelfState
trigger1 = (Vel y > 0) && (Pos y >= 0)
value = 5100
```

**Output (ZSS)**
```
#============================================================
# State 1026
#============================================================

[StateDef 1026;
	type: A;
	movetype: H;
	physics: N;
]

# Velocity
if Time = 0 {
	HitVelSet{x: 1; y: 1}
}

# Gravity
VelAdd{y: .45}

# No scroll
if Pos y < -15 {
	if BackEdgeBodyDist < 65
	|| FrontEdgeBodyDist < 65 {
		ScreenBound{value: 1; movecamera: 0,1}
	}
}

# Hit wall
if Pos y < -15 {
	if BackEdgeBodyDist <= 20
	|| FrontEdgeBodyDist <= 20 {
		ChangeState{value: 1027}
	}
}

# Hit ground
if (Vel y > 0) && (Pos y >= 0) {
	SelfState{value: 5100}
}
```

## Requirements (source version)

- Python 3.6 or higher

No external libraries are needed. The GUI uses `tkinter`, which is included with standard Python.  
The GUI source code runs on Windows, macOS, and Linux. The pre‑built executable is for Windows only.  

## Acknowledgements

- Elecbyte (http://www.elecbyte.com/), creators of CNS and Mugen
- SuperSuehiro, creator of ZSS and Ikemen

## Notes

This project is an AI-assisted work.
