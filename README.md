# PLR Game of life

This repository implements Conway's Game of Life, on a liquid handling robot and plate reader using [PyLabRobot](https://github.com/PyLabRobot/PyLabRobot).

TODO: Upload video

The state of the game is saved only on the plate. You start the game by manually pipetting a seed state onto the plate.

* Dye: 0.05 mM crystal violet.
* Volume: 100 uL in "living" wells, 0 uL in "dead" wells.
* Plate: 96 well costar ez wash.
* Optical depth reading wavelength: 580 nm.
* Optical depth threshold for "living": 0.3.

Someone suggested this idea to me a couple of months ago in the Sculpting Evo break room, but unfortunately I forgot who. If that's you, please let me know.
