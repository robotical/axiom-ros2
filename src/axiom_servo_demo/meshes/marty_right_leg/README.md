# Marty right-leg preview assets

The eight STL meshes and visual/joint geometry in `../../urdf/right_leg.urdf`
come from Robotical's `marty2_description` package in
[marty-ros2, revision 3e1e8816c3124d79524fc2138bc6e762a6519f32](https://github.com/robotical/marty-ros2/tree/3e1e8816c3124d79524fc2138bc6e762a6519f32/src/marty2_description).
They retain that package's **Apache-2.0** licence; see the accompanying `LICENSE`
and contributor attribution in `NOTICE`.
Meshes are copied without alteration. The servo adapter's own code remains MIT.

The derived URDF includes only the right leg, with these preview adaptations:

- An empty `axiom_servo_demo_base` replaces the robot's head/body as the root.
  The hip mounting point is placed 0.15 m above the preview grid.
- The actuated `leg_right_thigh_joint` is named `servo_joint` so it follows the
  existing single slider. The rear thigh and upper knee retain their original
  coupled motion, with mimic references updated to `servo_joint`.
- Twist, shin and foot joints are fixed at zero. They do not command additional
  servos. Inertial and collision geometry are omitted from this visual preview.
- Mesh URIs reference this package so no separate Marty checkout is required.

This is a target preview using the source model's neutral pose and axis direction.
It does not establish the physical servo's zero, direction, calibration or measured
position. Choose limits suitable for the attached mechanism.
