from pathlib import Path
import subprocess

base = Path(__file__).parent
common = '''
  graph [bgcolor="white", rankdir=TB, pad="0.25", nodesep="0.35", ranksep="0.5", fontname="Helvetica", dpi=180];
  node [fontname="Helvetica", fontsize=17, fontcolor="#203638", color="#81999d", penwidth=1.3, margin="0.16,0.12", shape=box, style=filled, fillcolor="white"];
  edge [fontname="Helvetica", fontsize=13, color="#517979", fontcolor="#49676d", penwidth=1.4, arrowsize=0.75];
'''
graphs = {
'ros2-thermal-graph': r'''
  driver [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="/axiom/axiom_bridge_node"];
  grid [label="/axiom/bus_BUS/device_ADDRESS/thermal/grid\naxiom_interfaces/msg/ThermalGrid"];
  adapter [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="/sensing/thermal_grid_visualizer"];
  markers [label="/sensing/thermal_heatmap\nvisualization_msgs/msg/Marker"];
  labels [label="/sensing/thermal_heatmap_labels\nvisualization_msgs/msg/MarkerArray"];
  rviz [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="/rviz2"];
  driver -> grid -> adapter;
  adapter -> markers -> rviz;
  adapter -> labels -> rviz;
  {rank=same; markers; labels;}
''',
'ros2-accelerometer-graph': r'''
  driver [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="/axiom/axiom_bridge_node"];
  imu [label="/axiom/bus_BUS/device_ADDRESS/imu/data_raw\nsensor_msgs/msg/Imu"];
  echo [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="ros2 topic echo … --once\ntemporary ROS subscriber"];
  driver -> imu [label="publishes • best effort / volatile"];
  imu -> echo [label="subscribes • best effort"];
''',
'ros2-overview-graph': r'''
  board [shape=box, style="rounded,filled", fillcolor="#f2f4f5", color="#abb8bc", label="Axiom + attached sensors\nHardware"];
  driver [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="/axiom/axiom_bridge_node"];
  devices [label="/axiom/devices\n/axiom/device_metadata\nInventory + descriptors"];
  measures [label="/axiom/bus_BUS/device_ADDRESS/…\nsample • data • typed measurements"];
  diagnostics [label="/axiom/diagnostics\n/axiom/raw/devjson\n/axiom/serial_console"];
  consumer [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="Your ROS nodes\nor ros2 topic echo"];
  dashboard [shape=ellipse, style="filled,dashed", fillcolor="#e9f3f2", color="#3b7b75", label="/dashboard\nOptional scenarios guide"];
  board -> driver [label="USB serial or Wi-Fi WebSocket", dir=both];
  driver -> devices;
  driver -> measures;
  driver -> diagnostics;
  devices -> dashboard [style=dashed, label="devices only"];
  measures -> consumer;
  {rank=same; devices; measures; diagnostics;}
  {rank=same; consumer; dashboard;}
''',
'ros2-services-graph': r'''
  client [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="Your ROS node\nor ros2 service call"];
  services [label="/axiom/connect • disconnect • get_connection_state\n/axiom/publish_data_subscription • set_sample_rate\n/axiom/ric_rest_url • ping\n/axiom/bus_BUS/device_ADDRESS/commands/COMMAND"];
  driver [shape=ellipse, fillcolor="#e9f3f2", color="#3b7b75", label="/axiom/axiom_bridge_node"];
  client -> services [dir=both, style=dashed, label="request / response"];
  services -> driver [dir=both, style=dashed, label="service server"];
''',
}
for name, content in graphs.items():
    path = base / (name + '.dot')
    path.write_text('digraph ros {\n' + common + content + '\n}\n')
    subprocess.run(['dot','-Tpng',str(path),'-o',str(base/(name+'.png'))], check=True)
    subprocess.run(['dot','-Tsvg',str(path),'-o',str(base/(name+'.svg'))], check=True)
    print(base/(name+'.png'))
