import Game.Levels.Tutorial.L01rfl
import Game.Levels.Tutorial.L02rw
import Game.Levels.Tutorial.L03two_eq_ss0
import Game.Levels.Tutorial.L04rw_backwards
import Game.Levels.Tutorial.L05add_zero
import Game.Levels.Tutorial.L06add_zero2
import Game.Levels.Tutorial.L07add_succ
import Game.Levels.Tutorial.L08twoaddtwo
/-!

# Tutorial world

This file defines Tutorial World. Like all worlds, this world
has a name, a title, an introduction, and most importantly
a finite set of levels (imported above). Each level has a
level number defined within it, and that's what determines
the order of the levels.
-/
World "Tutorial"
Title "Tutorial World"

Introduction
"Welcome to Tutorial World, {name}! Here you'll learn the basics of
proving theorems. Your goal for this chapter: prove that `2 + 2 = 4`.

You'll prove theorems by solving puzzles with tools called *tactics*.
Apply the right tactics in the right order, and the proof is yours.

Let's learn some basic tactics -- tap Skip whenever you're ready to dive in.
"
