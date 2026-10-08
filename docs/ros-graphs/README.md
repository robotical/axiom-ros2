# ROS guide diagrams

Diagrams used on the Axiom ROS 2 overview, accelerometer and thermal-camera
userguides. They describe expected data flow, not a live ROS graph. Device topic
boxes in the overview group related topics. BUS and ADDRESS are discovered
identities; optional tools only appear when launched.

The diagrams follow the manual `/axiom` walkthroughs. The thermal visualiser is
launched under `/sensing`. Other namespaces, aliases and launches can produce a
different graph. ROS parameter services, `/rosout` and `/parameter_events` are
omitted for clarity.

Edit `render.py`, then regenerate the PNG, SVG and DOT files with Graphviz:

```bash
python3 docs/ros-graphs/render.py
```

Check interface names against `src/axiom_driver/README.md` and the corresponding
node source before updating the userguides.
