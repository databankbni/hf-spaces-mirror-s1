#!/opt/homebrew/bin/bash
# run_gumball_movies.sh -- serial batch runner for 10 Gumball movie-scene prompts
set -uo pipefail
cd "$(dirname "$0")"          # h3.c dir
mkdir -p outputs

MODEL="$HOME/Documents/mlx-vlm/MiniMax-H3"
W=256 H=256 F=362 S=50 L=50 R=1
SKIP=""                       # empty string to run all

declare -A P=()

P[0000]="Scene: Gumball and Darwin standing on a rocky hill at dawn, recreating the iconic scene from The Lion King.
Action: Gumball holds Darwin up triumphantly while other Elmore students gather below, the sun rising over the school playground as animals from the school petting zoo look on.
Camera: low-angle dramatic shot looking up at the pair, 24 mm wide lens, slow crane movement rising, golden sunrise breaking over the horizon.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, epic African savanna aesthetic with school playground elements, warm sunrise palette.
Audio: powerful African-inspired orchestral score. Gumball says: \"Everything the light touches is our kingdom.\" Darwin replies: \"But Gumball, that is just the soccer field.\""

P[0001]="Scene: Gumball and Darwin in a snowy mountain landscape, recreating the iconic scene from The Shining.
Action: Gumball chases Darwin through a snowy hedge maze with a foam baseball bat, Darwin leaving tiny footprints in the snow as Gumball shouts dramatically.
Camera: aerial tracking shot following the chase through the maze, 35 mm lens, slow sweeping movement, snow falling gently.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, horror aesthetic with bright snow contrast, eerie shadows in the maze.
Audio: ominous orchestral music with heartbeat rhythm. Gumball shouts: \"Here's Gumball!\" Darwin yells: \"This is not how you play hide and seek!\""

P[0002]="Scene: Gumball and Darwin running through a train station, recreating the platform scene from Harry Potter.
Action: Gumball pushes a luggage cart loaded with schoolbooks while Darwin sits on top, both running toward a brick wall between platforms, other students watching in confusion.
Camera: high-speed tracking shot following the cart, 28 mm lens, dynamic movement, motion blur on the station background.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, magical British boarding school aesthetic with Elmore twist, steam and mist effects.
Audio: whimsical magical orchestral score. Gumball says: \"Darwin, we have to run at the wall!\" Darwin replies: \"I trust you, but this seems like a very bad idea!\""

P[0003]="Scene: Gumball and Darwin in a boxing ring, recreating the final fight from Rocky.
Action: Gumball and Darwin face off in a school gym boxing ring, both wearing oversized boxing gloves, exhausted but determined as the crowd of students cheers wildly.
Camera: low-angle tracking shot from the ropes, dynamic movement, dramatic lighting from overhead gym lights.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, sports drama aesthetic with gritty gym atmosphere, sweat and determination.
Audio: triumphant training anthem with horns. Gumball says: \"Darwin, no matter what happens, you are my best friend.\" Darwin says: \"Gumball, I love you, but I am going to win this.\""

P[0004]="Scene: Gumball and Darwin climbing a snowy mountain, recreating the expedition scene from Everest.
Action: Gumball leads Darwin up a steep snowy slope using a jump rope as a climbing rope, both wearing winter coats made from old blankets, wind howling around them.
Camera: wide aerial shot of the mountain face, 35 mm lens, slow zoom in on the tiny figures climbing.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, survival drama aesthetic with harsh white snow, dramatic storm clouds.
Audio: tense orchestral score with wind sounds. Gumball says: \"We are almost there, Darwin!\" Darwin replies: \"I cannot feel my fins! This is worse than gym class!\""

P[0005]="Scene: Gumball and Darwin in a gladiator arena, recreating the battle scene from Gladiator.
Action: Gumball stands in a makeshift arena wearing cardboard armor while Darwin watches from the stands, other students dressed as Roman soldiers surrounding the arena.
Camera: sweeping crane shot over the arena, 35 mm lens, dramatic movement following the action.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, epic historical epic aesthetic with school playground elements, dramatic lighting.
Audio: epic orchestral score with battle drums. Gumball shouts: \"Are you not entertained?\" Darwin yells: \"Gumball, this is just recess!\""

P[0006]="Scene: Gumball and Darwin standing at a crossroads at night, recreating the deal scene from Crossroads.
Action: Gumball holds a guitar case while Darwin holds a tiny harmonica, both looking down a dark country road with a single streetlight, fog rolling across the pavement.
Camera: dramatic low-angle shot with deep shadows, 30 mm lens, slow rotation around the characters.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, blues music drama aesthetic with moody lighting, mysterious atmosphere.
Audio: blues guitar riff with harmonica accompaniment. Gumball says: \"Darwin, this is where we make our choice.\" Darwin says: \"I choose home. Home has snacks.\""

P[0007]="Scene: Gumball and Darwin in a subway station, recreating the train scene from The Warriors.
Action: Gumball and Darwin run through a subway station being chased by rival student gangs, both looking back nervously as they sprint toward a train.
Camera: high-speed tracking shot from behind, 28 mm lens, dynamic handheld movement, dramatic lighting in the tunnel.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, gritty 1970s action aesthetic with neon signs and graffiti.
Audio: intense chase music with percussion. Gumball yells: \"Come out to play!\" Darwin shouts: \"Gumball, this is not the time for movie quotes!\""

P[0008]="Scene: Gumball and Darwin in a science lab, recreating the experiment scene from Frankenstein.
Action: Gumball activates a science fair volcano while Darwin watches nervously, electricity crackling as the volcano erupts with glowing purple foam.
Camera: circular camera movement around the lab, 30 mm lens, dynamic angles showing bubbling beakers and electrical arcs.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, gothic science experiment aesthetic with purple lighting, dramatic shadows.
Audio: dramatic orchestral music with electrical crackling. Gumball says: \"It is alive! ALIVE!\" Darwin says: \"It is just baking soda and vinegar, Gumball!\""

P[0009]="Scene: Gumball and Darwin on a desert road, recreating the final scene from Thelma and Louise.
Action: Gumball and Darwin sit in a toy car at the edge of a sandbox cliff, looking at each other with determination as the sun sets over the playground desert.
Camera: wide shot of the car at the cliff edge, 35 mm lens, golden hour lighting, slow zoom out to show the vast sandbox landscape.
Look: mixed-media cartoon style faithful to The Amazing World of Gumball, dramatic road trip aesthetic with warm desert colors.
Audio: emotional orchestral score with country undertones. Gumball says: \"Darwin, let's keep going.\" Darwin replies: \"Gumball, the car is stuck in the sandbox.\""

run() {
  local name="$1"
  local rc

  [[ " $SKIP " == *" $name "* ]] && { echo "skipping $name"; return 0; }

  {
    SECONDS=0
    echo "Start: $(date '+%Y-%m-%d %H:%M:%S') [$name] [Job PID: $BASHPID]"

    ./h3 --profile -d "$MODEL" -p "${P[$name]}" \
      --width "$W" --height "$H" --frames "$F" --steps "$S" \
      --layers "$L" --reuse "$R" \
      -o "outputs/${name}_gumball_movies.mp4" &
    local h3_pid=$!
    
    echo "H3 Process PID: $h3_pid"
    wait $h3_pid
    rc=$?
    
    echo "End: $(date '+%Y-%m-%d %H:%M:%S') (elapsed ${SECONDS}s) rc=$rc [Job PID: $BASHPID]"
  } 2>&1 | tee "outputs/${name}_gumball_movies.log"
}

for k in $(printf '%s\n' "${!P[@]}" | sort); do
  run "$k"
done
echo "Batch complete. All 10 Gumball movie scenes rendered!"