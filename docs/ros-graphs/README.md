# ROS guide diagrams

Diagrams used on the Axiom ROS 2 overview, accelerometer and thermal-camera
userguides. They describe expected data flow, not a live ROS graph. Device topic
boxes in the overview group related topics. BUS and ADDRESS are discovered
identities; optional tools only appear when launched. Namespaces are examples,
not identifiers for particular boards. The overview groups the main topic families;
standard `thermal/image` and `range/image` are additional outputs.

The diagrams follow the manual `/axiom` walkthroughs. The thermal visualiser is
launched under `/sensing`. Other namespaces, aliases and launches can produce a
different graph. ROS parameter services, `/rosout` and `/parameter_events` are
omitted for clarity.

For user workflows, see the [README](../../README.md),
[thermal RViz](../thermal-camera.md) and [Foxglove](../../examples/foxglove/README.md).

For diagram maintenance, run from the repository root. Edit `render.py`, then
regenerate the PNG, SVG and DOT files with Graphviz:

```bash
python3 docs/ros-graphs/render.py
```

Check interface names against `src/axiom_driver/README.md` and the corresponding
node source before updating the userguides.
