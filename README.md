# ushabti

A simple sandbox so you can give Claude free range, but only over one folder

## Installation

1. Install docker 
2. Clone this repo
3. Put ushabti.py on your `PATH`, e.g. `ln -s ~/projects/ushabti/ushabti.py ~/.local/bin/u`
4. Tell Claude how to use it, e.g. put this in `CLAUDE.md`:

> # sandbox
> The `u` prefix runs commands in a sandbox which mounts the current dir, and you can run *any* command prefixed with u.
> e.g. `u "ls | wc"` to use pipe. The sandbox persists, but `u kill` will take it down (and the next u command will bring up a fresh container). Killing `u sleep 3600` may not propagate the kill to the sandbox's process, so you might have to do `u pkill ...` afterwards

5. Add an allowed directory to `~/.config/ushabti/config.yaml`, e.g.

``` yaml
# WARNING: Do not mount the directory containing ushabti.py itself.
# That would allow the sandboxed user to modify ushabti.py and escape the sandbox
- dir: ~/my-project
  image: ubuntu:latest
```

## Etymology

From [wiktionary](https://en.wiktionary.org/wiki/ushabti):
> In Ancient Egypt, a figurine of a dead person, placed in their tomb to do their work for them in the afterlife.

i.e. an ushabti does work for you, and it's found in a box in the desert, a sandbox
