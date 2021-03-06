from os.path import join

import pyglet.resource
import os.path
from cocos import director
from cocos.scene import Scene
from cocos.layer import MultiplexLayer

from match3cocos2d.HUD import BackgroundLayer
from match3cocos2d.Menus import MainMenu


def main():
    script_dir = os.path.dirname(os.path.realpath(__file__))

    pyglet.resource.path = [join(script_dir, '..')]
    pyglet.resource.reindex()

    director.director.init(width=800, height=650, caption="StudentDays")
    # bg_layer = BackgroundLayer()
    scene = Scene()
    # scene.add(bg_layer, z=0)
    scene.add(MultiplexLayer(
        MainMenu()
    ),
        z=1)

    director.director.run(scene)


if __name__ == '__main__':
    main()
