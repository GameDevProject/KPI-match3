import random

from cocos.actions import ScaleTo, RotateTo, CallFuncS, ScaleBy, Reverse, MoveTo, CallFunc

__all__ = ['GameModel']

import pyglet
import os.path
import sys
from os.path import join, isdir, basename
from random import choice, randint
from glob import glob
from cocos.sprite import Sprite
from cocos import *
from match3cocos2d.my_status import status
from match3cocos2d.db_models import *
CELL_WIDTH, CELL_HEIGHT = 100, 100
ROWS_COUNT, COLS_COUNT = 6, 8

# Game State Values
WAITING_PLAYER_MOVEMENT = 1
PLAYER_DOING_MOVEMENT = 2
SWAPPING_TILES = 3
IMPLODING_TILES = 4
DROPPING_TILES = 5
GAME_OVER = 6


class GameModel(pyglet.event.EventDispatcher):
    def __init__(self):
        super(GameModel, self).__init__()
        self.tile_grid = {}  # Dict emulated sparse matrix, key: tuple(x,y), value : tile_type
        self.imploding_tiles = []  # List of tile sprites being imploded, used for IMPLODING_TILES
        self.dropping_tiles = []  # List of tile sprites being dropped, used during DROPPING_TILES
        self.swap_start_pos = None  # Position of the first tile clicked for swapping
        self.swap_end_pos = None  # Position of the second tile clicked for swapping
        # the replace is for windows compatibilty
        script_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), '..')
        os.chdir(script_dir)
        if isdir('images'):
            image_base_path = join(script_dir, 'images')
        else:
            image_base_path = join(sys.prefix, 'share', 'match3cocos2d', 'images')
        pyglet.resource.path = [image_base_path]
        pyglet.resource.reindex()
        session = Session()
        self.player = session.query(User).first()
        session.close()
        self.level = None

        # self.available_tiles = [basename(s) for s in glob(join(image_base_path, '*.png'))]
        self.available_tiles = []

        self.game_state = WAITING_PLAYER_MOVEMENT
        self.objectives = []
        self.on_game_over_pause = 0

    def start(self):
        self.set_next_level()

    def set_next_level(self):
        session = Session()
        self.player = session.query(User).first()
        self.level = session.query(Level).filter_by(
            id=self.player.current_level).first()
        if not self.level:
            self.game_state = GAME_OVER
            self.dispatch_event("on_game_win")
            return

        tiles = session.query(Tile).filter_by(level=self.level.id).all()
        self.available_tiles = [tile.location for tile in tiles]
        session.close()
        self.dispatch_event("on_level_start")
        self.play_time = self.max_play_time = 120
        for elem in self.imploding_tiles + self.dropping_tiles:
            self.view.remove(elem)
        self.on_game_over_pause = 0
        self.fill_with_random_tiles()
        self.set_objectives()
        self.dispatch_event("on_update_objectives")
        pyglet.clock.unschedule(self.time_tick)
        pyglet.clock.schedule_interval(self.time_tick, 1)

    def time_tick(self, delta):
        self.play_time -= 1
        self.dispatch_event("on_update_time", self.play_time / float(self.max_play_time))
        if self.play_time == 0 and self.game_state != GAME_OVER:
            pyglet.clock.unschedule(self.time_tick)
            self.game_state = GAME_OVER
            self.dispatch_event("on_game_over")

    def set_objectives(self):
        session = Session()
        objectives = session.query(Objective).filter_by(
            level=self.level.id).all()
        level_objectives = []
        for o in objectives:
            tile = session.query(Tile).filter_by(id=o.tile).first()
            sprite = self.tile_sprite(tile.location, (0, 0))
            level_objectives.append([tile.location, sprite, o.number])

        self.objectives = level_objectives

    def fill_with_random_tiles(self):
        """
        Fills the tile_grid with random tiles
        """
        for elem in [x[1] for x in self.tile_grid.values()]:
            self.view.remove(elem)
        tile_grid = {}
        # Fill the data matrix with random tile types
        while True:  # Loop until we have a valid table (no imploding lines)
            for x in range(COLS_COUNT):
                for y in range(ROWS_COUNT):
                    tile_type, sprite = choice(self.available_tiles), None
                    tile_grid[x, y] = tile_type, sprite
            if len(self.get_same_type_lines(tile_grid)) == 0:
                break
            tile_grid = {}

        # Build the sprites based on the assigned tile type
        for key, value in tile_grid.items():
            tile_type, sprite = value
            sprite = self.tile_sprite(tile_type, self.to_display(key))
            tile_grid[key] = tile_type, sprite
            self.view.add(sprite)

        self.tile_grid = tile_grid

    def swap_elements(self, elem1_pos, elem2_pos):
        tile_type, sprite = self.tile_grid[elem1_pos]
        self.tile_grid[elem1_pos] = self.tile_grid[elem2_pos]
        self.tile_grid[elem2_pos] = tile_type, sprite

    def implode_lines(self):
        """
        :return: Implodes lines with more than 3 elements of the same type
        """
        implode_count = {}
        for x, y in self.get_same_type_lines(self.tile_grid):
            if not self.tile_grid[x, y]:
                continue
            tile_type, sprite = self.tile_grid[x, y]
            session = Session()
            tile = session.query(Tile).filter_by(location=tile_type).first()

            self.tile_grid[x, y] = None
            self.imploding_tiles.append(sprite)  # Track tiles being imploded
            if tile.implode:
                name_to_implode = session.query(Tile).filter_by(id=tile.implode).first().location
                may_be_imploded = [t for t in self.tile_grid.keys()
                                   if self.tile_grid[t] and self.tile_grid[t][0] == name_to_implode]
                if may_be_imploded:
                    tile_to_implode = random.choice(may_be_imploded)
                    tile_sprite = self.tile_grid[tile_to_implode][1]
                    self.tile_grid[tile_to_implode] = None
                    self.imploding_tiles.append(tile_sprite)
                    tile_sprite.do(
                        ScaleTo(0, 0.5) | RotateTo(180, 0.5) + CallFuncS(
                                self.on_tile_remove))

            session.close()
            # Implode animation
            sprite.do(ScaleTo(0, 0.5) | RotateTo(180, 0.5) + CallFuncS(self.on_tile_remove))

            if tile.can_add_objectives and self.objectives:
                o = random.choice(self.objectives)
                if o[2]:
                    o[2] += 1
            implode_count[tile_type] = implode_count.get(tile_type, 0) + 1
        # Decrease counter for tiles matching objectives
        for elem in self.objectives:
            if elem[0] in implode_count:
                Scale = ScaleBy(1.5, 0.2)
                elem[2] = max(0, elem[2] - implode_count[elem[0]])
                elem[1].do((Scale + Reverse(Scale)) * 3)
        # Remove objectives already completed
        self.objectives = [elem for elem in self.objectives if elem[2] > 0]
        if len(self.imploding_tiles) > 0:
            self.game_state = IMPLODING_TILES  # Wait for the implosion animation to finish
            pyglet.clock.unschedule(self.time_tick)
        else:
            if len(self.objectives) == 0:
                pyglet.clock.unschedule(self.time_tick)
                session = Session()
                player = session.query(User).first()
                player.current_level += 1
                # session.add(self.player)
                session.commit()
                session.close()
                self.dispatch_event("on_level_completed")
            self.game_state = WAITING_PLAYER_MOVEMENT
            pyglet.clock.schedule_interval(self.time_tick, 1)
        return self.imploding_tiles

    def drop_groundless_tiles(self):
        """
        Walk on all columns, from bottom to up:
            a) count gap or move down pieces for gaps already counted
            b) on top drop as much tiles as gaps counted
        :return:
        """
        tile_grid = self.tile_grid

        for x in range(COLS_COUNT):
            gap_count = 0
            for y in range(ROWS_COUNT):
                if tile_grid[x, y] is None:
                    gap_count += 1
                elif gap_count > 0:  # Move from y to y-gap_count
                    tile_type, sprite = tile_grid[x, y]
                    if gap_count > 0:
                        sprite.do(MoveTo(self.to_display((x, y - gap_count)), 0.3 * gap_count))
                    tile_grid[x, y - gap_count] = tile_type, sprite
            for n in range(gap_count):  # Drop as much tiles as gaps counted
                tile_type = choice(self.available_tiles)
                sprite = self.tile_sprite(tile_type, self.to_display((x, y + n + 1)))
                tile_grid[x, y - gap_count + n + 1] = tile_type, sprite
                sprite.do(
                    MoveTo(self.to_display((x, y - gap_count + n + 1)), 0.3 * gap_count) +
                    CallFuncS(self.on_drop_completed))
                self.view.add(sprite)
                self.dropping_tiles.append(sprite)

    def on_drop_completed(self, sprite):
        self.dropping_tiles.remove(sprite)
        if len(self.dropping_tiles) == 0:  # All tile dropped
            self.implode_lines()  # Check for new implosions

    def on_tile_remove(self, sprite):
        status.score += 1
        self.imploding_tiles.remove(sprite)
        self.view.remove(sprite)
        if len(self.imploding_tiles) == 0:  # Implosion complete, drop tiles to fill gaps
            self.dispatch_event("on_update_objectives")
            self.drop_groundless_tiles()

    def set_controller(self, controller):
        self.controller = controller

    def set_view(self, view):
        self.view = view

    def tile_sprite(self, tile_type, pos):
        """
        :param tile_type: numeric id, must be in the range of available images
        :param pos: sprite position
        :return: sprite built form tile_type
        """
        sprite = Sprite(tile_type)
        sprite.position = pos
        sprite.scale = 1
        return sprite

    def on_tiles_swap_completed(self):
        self.game_state = DROPPING_TILES
        if len(self.implode_lines()) == 0:
            # No lines imploded, roll back the game play

            # Start swap animation for both objects
            tile_type, sprite = self.tile_grid[self.swap_start_pos]
            sprite.do(MoveTo(self.to_display(self.swap_end_pos), 0.4))
            tile_type, sprite = self.tile_grid[self.swap_end_pos]
            sprite.do(MoveTo(self.to_display(self.swap_start_pos), 0.4) +
                CallFunc(self.on_tiles_swap_back_completed))

            # Revert on the grid
            self.swap_elements(self.swap_start_pos, self.swap_end_pos)
            self.game_state = SWAPPING_TILES

    def on_tiles_swap_back_completed(self):
        self.game_state = WAITING_PLAYER_MOVEMENT

    def to_display(self, row_col):
        """
        :param row:
        :param col:
        :return: (x, y) from display coordinates from the bi-dimensional ( row, col) array position
        """
        row, col = row_col
        return CELL_WIDTH / 2 + row * CELL_WIDTH, CELL_HEIGHT / 2 + col * CELL_HEIGHT

    def to_model_pos(self, view_x_y):
        view_x, view_y = view_x_y
        return int(view_x / CELL_WIDTH), int(view_y / CELL_HEIGHT)

    def get_same_type_lines(self, tile_grid, min_count=3):
        """
        Identify vertical and horizontal lines composed of min_count consecutive elements
        :param min_count: minimum consecutive elements to identify a line
        """
        all_line_members = []

        # Check for vertical lines
        for x in range(COLS_COUNT):
            same_type_list = []
            last_tile_type = None
            for y in range(ROWS_COUNT):
                tile_type, sprite = tile_grid[x, y]
                if last_tile_type == tile_type:
                    same_type_list.append((x, y))
                # Line end because type changed or edge reached
                if tile_type != last_tile_type or y == ROWS_COUNT - 1:
                    if len(same_type_list) >= min_count:
                        all_line_members.extend(same_type_list)
                    last_tile_type = tile_type
                    same_type_list = [(x, y)]

        # Check for horizontal lines
        for y in range(ROWS_COUNT):
            same_type_list = []
            last_tile_type = None
            for x in range(COLS_COUNT):
                tile_type, sprite = tile_grid[x, y]
                if last_tile_type == tile_type:
                    same_type_list.append((x, y))
                # Line end because of type change or edge reached
                if tile_type != last_tile_type or x == COLS_COUNT - 1:
                    if len(same_type_list) >= min_count:
                        all_line_members.extend(same_type_list)
                    last_tile_type = tile_type
                    same_type_list = [(x, y)]

        # Remove duplicates
        all_line_members = list(set(all_line_members))
        return all_line_members

    @staticmethod
    def is_valid_position(x, y):
        return 0 < y < ROWS_COUNT * CELL_HEIGHT and COLS_COUNT * CELL_WIDTH > x > 0

    def on_mouse_press(self, x, y):
        if self.game_state == WAITING_PLAYER_MOVEMENT and self.is_valid_position(x, y):

            self.swap_start_pos = self.to_model_pos((x, y))
            self.game_state = PLAYER_DOING_MOVEMENT

    def on_mouse_drag(self, x, y):
        if self.game_state != PLAYER_DOING_MOVEMENT:
            return

        start_x, start_y = self.swap_start_pos
        self.swap_end_pos = new_x, new_y = self.to_model_pos((x, y))

        distance = abs(new_x - start_x) + abs(new_y - start_y)  # horizontal + vertical grid steps

        # Ignore movement if not at 1 step away from the initial position
        if new_x < 0 or new_y < 0 or distance != 1 or not self.is_valid_position(x, y):
            return

        # Start swap animation for both objects
        tile_type, sprite = self.tile_grid[self.swap_start_pos]
        sprite.do(MoveTo(self.to_display(self.swap_end_pos), 0.4))
        tile_type, sprite = self.tile_grid[self.swap_end_pos]
        sprite.do(MoveTo(self.to_display(self.swap_start_pos), 0.4) +
            CallFunc(self.on_tiles_swap_completed))

        # Swap elements at the board data grid
        self.swap_elements(self.swap_start_pos, self.swap_end_pos)
        self.game_state = SWAPPING_TILES

    def dump_table(self):
        """
        :return: Prints the play table, for debug
        """
        for y in range(ROWS_COUNT - 1, -1, -1):
            line_str = ''
            for x in range(COLS_COUNT):
                line_str += str(self.tile_grid[x, y][0])
            print(line_str)


GameModel.register_event_type('on_update_objectives')
GameModel.register_event_type('on_update_time')
GameModel.register_event_type('on_game_over')
GameModel.register_event_type('on_game_win')
GameModel.register_event_type('on_level_start')
GameModel.register_event_type('on_level_completed')
