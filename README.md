# Cafe Blend Story

Offline single-player trainer for the Steam release of Cafe Blend Story / Cafe Master Story.

## What can realistically be modified?

I checked the shipped IL2CPP metadata from the game directory and found save/runtime symbols around:

- `Money` / `AddMoney`
- `ResearchPoint` / `AddResearchPoint`
- `SatisfactionPoint`
- `TownData`
- `StaffManager`
- `Facility`
- unlock and item related flags

Public community cheat tables for this game also line up with that picture: money, research points, facility values, unlocks, and staff-related data are all likely reachable.

## Why this repository uses an external scanner first

The Steam build stores game logic in IL2CPP native code, and the save files are not plain JSON or plain text. A one-click static trainer based on hard-coded addresses would be brittle across updates and across sessions.

So this repo starts with the most practical version first:

- a Windows trainer that attaches to `KairoGames.exe`
- scans 32-bit integer values in writable memory
- refines matches after the value changes in-game
- writes the new value back
- can freeze the value afterward
- now also includes experimental one-click patches for a few IL2CPP runtime data tables

That makes the current version reliable for:

- money
- research points
- any other 32-bit integer you can identify manually
- menu and cooking unlock states through direct IL2CPP table patching
- food / topping unlock and max-rank attempts after those tables are initialized in-game

## Files

- `trainer.py`: Tkinter GUI trainer plus a local `--self-test` mode

## Requirements

- Windows
- Python 3.10 or newer
- The game running locally

No third-party Python packages are required.

## Usage

1. Start Cafe Blend Story and load the save you want to modify.
2. Run:

```powershell
python .\trainer.py
```

3. In the app, attach to `KairoGames.exe`.
4. Enter the number you currently see in-game, for example your money.
5. Press `New Scan`.
6. Change that number in-game.
7. Enter the new visible number and press `Refine`.
8. Repeat until the candidate count is small.
9. Enter your desired value and press `Set Value`.
10. If you want it to stay fixed, enable `Freeze`.

## Experimental One-Click Patches

The current trainer also has two experimental buttons:

- `Unlock Recipes / Menus`
- `Max Rank / Stock`

These do **not** use the slow generic integer scan. Instead, they resolve a few known IL2CPP runtime tables from the current build and patch those objects directly.

What is currently wired:

- `MenuData`
- `CookingMenuData`
- `Food` when the related runtime table has been initialized
- `ToppingData` when the related runtime table has been initialized

Practical note:

- If `Food` or `ToppingData` says the type is not initialized yet, open the related in-game menu once and try again.

## Self-test

You can verify the memory scanner path without opening the game:

```powershell
python .\trainer.py --self-test
```

This runs the scanner against the current Python process, changes a test integer in memory, and confirms both the manual scan path and the experimental batch-patch path still work.

## Current limitations

- It assumes the target value is a 32-bit signed integer.
- The manual scanner still needs a fresh scan after each game launch.
- The one-click patch path currently covers only a subset of data tables.
- Shop item states, facilities, staff values, and broader unlock flags still need deeper reverse engineering before they can be exposed as dependable dedicated buttons.

## Next steps

If you want to extend this further, the most promising follow-up work is:

1. Recover the concrete runtime structures behind `StaffManager`, `Facility`, and `TownData`.
2. Add typed scanners for booleans and small arrays.
3. Build one-click workflows for common actions like max money, max research, and selected unlocks.
