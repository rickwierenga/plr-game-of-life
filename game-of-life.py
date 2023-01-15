import asyncio
import logging

import numpy as np
import matplotlib.pylab as plt
from pylabrobot.liquid_handling import LiquidHandler, STAR
from pylabrobot.resources import set_volume_tracking
from pylabrobot.liquid_handling.standard import GripDirection
from pylabrobot.plate_reading import PlateReader, CLARIOStar
from pylabrobot.resources import Coordinate, Resource
from pylabrobot.resources import (
  TIP_CAR_480_A00,
  PLT_CAR_L5AC_A00,
  Cos_96_EZWash,
  HTF_L
)
from pylabrobot.resources.hamilton import STARLetDeck

set_volume_tracking(enabled=False)

OD_THRESHOLD = 0.3

ALIVE_VOLUME = 100

logging.getLogger("pylabrobot").setLevel(logging.DEBUG)


def build_deck():
  deck = STARLetDeck()

  tip_car = TIP_CAR_480_A00(name="tip carrier")
  tip_car[0] = HTF_L(name="tip rack")
  deck.assign_child_resource(tip_car, rails=3)

  plt_car = PLT_CAR_L5AC_A00(name="plate carrier")
  plt_car[1] = Cos_96_EZWash(name="plate")
  deck.assign_child_resource(plt_car, rails=15)

  trough = Resource(name="trough", size_x=44, size_y=127, size_z=25)
  deck.assign_child_resource(trough, location=Coordinate(290.9, 93.8, 4.5))

  plate_reader = PlateReader(name="plate_reader", backend=CLARIOStar())
  deck.assign_child_resource(plate_reader, location=Coordinate(979.5, 285.2-63, 200 - 100))

  return deck


async def read_plate(lh, pr, plate, plt_car):
  lh.move_plate(plate, pr, pickup_distance_from_top=8.2,
      get_direction=GripDirection.FRONT, put_direction=GripDirection.LEFT)

  await pr.close()

  # read the optical depth at 580 nm
  plate_reading = await pr.read_absorbance(wavelength=580, report="OD")
  plate_reading = np.asarray(plate_reading)

  await pr.open()

  # move plate out of the plate reader
  lh.move_plate(pr.get_plate(), plt_car[1], pickup_distance_from_top=8.2,
    get_direction=GripDirection.LEFT, put_direction=GripDirection.FRONT)

  return plate_reading

def save_figure(plate_reading, cycle):
    plt.figure(figsize=(30,40))
    plt.imshow(plate_reading)
    for (j,i), label in np.ndenumerate(plate_reading):
      plt.text(i,j, round(label, 2), ha="center", va="center", fontsize=24)
    plt.savefig(f"plate_reading_{cycle}.png", dpi=300)


def read_state(plate_reading):
  return plate_reading > OD_THRESHOLD


def compute_next_state(state):
  new_state = np.zeros(state.shape)

  for row in range(state.shape[0]):
    for column in range(state.shape[1]):
      living = state[max(row-1, 0):min(row+2, state.shape[0]), max(column-1, 0):min(column+2, state.shape[1])].sum() - state[row, column]
      if living < 2:
        new_state[row, column] = False
      elif living == 2:
        new_state[row, column] = state[row, column]
      elif living == 3:
        new_state[row, column] = True
      elif living > 3:
        new_state[row, column] = False

  return new_state


def update_plate(lh, trough, tip_rack, plate, diff):
  lh.pick_up_tips(tip_rack["A12:H12"])

  # Simulate the pipetting operations to compute how much volume much be pre-aspirated.
  # Tried re-using volume, but it's hard to get everything out and this accumulates over time.
  need = [0]*8
  excess = [0]*8
  for column in range(diff.shape[1]):
    for row in range(diff.shape[0]):
      if diff[row, column] == 1:
        need[row] += ALIVE_VOLUME
      elif diff[row, column] == -1:
        excess[row] += ALIVE_VOLUME

  # Aspirate for the wells that came to life.
  channels = []
  vols = []
  for channel in range(len(need)):
    if need[channel] > 0:
      vols.append(need[channel])
      channels.append(channel)

  if len(channels) > 0:
    print("aspirating from trough", channels, vols)
    lh.aspirate(trough, vols=vols, use_channels=channels, liquid_height=2)

  # Dispense into the wells that need liquid.
  for column in range(diff.shape[1]):
    # Dispense in wells where the next state is "alive" and the current state is "dead".
    # TODO: should provide "volume-hot" encoding conversion in the API
    channels = []
    well_ids = []
    vols = []
    for row in range(diff.shape[0]):
      if diff[row, column] == 1:
        vols.append(ALIVE_VOLUME)
        channels.append(row)
        well_ids.append(column * 8 + row)

    print("dispensing", column, channels, vols, well_ids)
    if len(well_ids) > 0:
      lh.dispense(plate[well_ids], vols=vols, use_channels=channels)

  # Aspirate from the wells that died.
  for column in reversed(range(diff.shape[1])): # "on the way back"
    # Aspirate in wells where the next state is "dead" and the current state is "alive".
    channels = []
    well_ids = []
    vols = []
    for row in range(diff.shape[0]):
      if diff[row, column] == -1:
        vols.append(ALIVE_VOLUME)
        channels.append(row)
        well_ids.append(column * 8 + row)

    print("aspirating", column, channels, vols, well_ids)
    if len(well_ids) > 0:
      lh.aspirate(plate[well_ids], vols=vols, use_channels=channels, liquid_height=0)

  # Dispense the remaining volume.
  channels = []
  vols = []
  for channel in range(len(need)):
    if excess[channel] > 0:
      vols.append(excess[channel])
      channels.append(channel)

  if len(channels) > 0:
    try:
      print("dispensing excess volume", channels, vols)
      lh.dispense(trough, vols=vols, use_channels=channels, liquid_height=2)
    except Exception as e:
      # This sometimes happens if we could not aspirate everything from the wells. In this case,
      # it's not actually a problem, so we just ignore the exception.
      print("Exception while dispensing: ", channel)
      print("Exception while dispensing: ", e)

  lh.return_tips()


async def main(max_cycles=100):
  deck = build_deck()
  lh = LiquidHandler(backend=STAR(read_timeout=120), deck=deck)
  lh.setup()

  pr = deck.get_resource("plate_reader")
  await pr.setup()

  plate = deck.get_resource("plate")
  plt_car = deck.get_resource("plate carrier")
  trough = deck.get_resource("trough")
  tip_rack = deck.get_resource("tip rack")

  cycle = 0

  await pr.open()

  while cycle < max_cycles:
    print("cycle", cycle)

    # move plate into the plate reader
    plate_reading = await read_plate(lh, pr, plate, plt_car)

    save_figure(plate_reading, cycle)

    current_state = read_state(plate_reading)
    next_state = compute_next_state(current_state)

    if (next_state == current_state).all():
      print("reached terminal state, stopping")
      break
    diff = (next_state - current_state)

    update_plate(lh, trough, tip_rack, plate, diff)    

    cycle += 1

  lh.stop()
  await pr.stop()


if __name__ == "__main__":
  asyncio.run(main())
