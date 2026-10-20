// Copyright 2026 Robotical. SPDX-License-Identifier: MIT
#ifndef AXIOM_LIGHT_PANEL__LIGHT_PANEL_HPP_
#define AXIOM_LIGHT_PANEL__LIGHT_PANEL_HPP_

#include <array>
#include <chrono>
#include <deque>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <vector>
#include <QColor>
#include <QJsonObject>
#include <rviz_common/panel.hpp>
#include <rclcpp/rclcpp.hpp>
#include <std_msgs/msg/color_rgba.hpp>
#include <std_msgs/msg/string.hpp>
#include <axiom_interfaces/srv/device_command.hpp>

class QComboBox;
class QLabel;
class QPushButton;
class QSpinBox;
class QTimer;
class QWidget;

namespace axiom_light_panel
{
class LightPanel : public rviz_common::Panel
{
  Q_OBJECT
public:
  explicit LightPanel(QWidget * parent = nullptr);
  ~LightPanel() override;
  void onInitialize() override;
  // Also supports embedding the same panel in a ROS/Qt integration test.
  void setRosNode(rclcpp::Node::SharedPtr node);

private:
  using Command = axiom_interfaces::srv::DeviceCommand;
  using Clock = std::chrono::steady_clock;
  struct Event {std::string topic; std::string json;};
  struct Inbox {std::mutex mutex; std::deque<Event> events;};
  struct Source {QJsonObject devices; Clock::time_point seen;};
  void tick();
  void refreshLights();
  void selectLight();
  void chooseColour();
  void sendCommand(const QString & path, const std::vector<double> & values);
  void requestColour(const QColor & colour);
  QString resolve(const QString & path) const;
  QString service(const QString & name) const;
  void controls(bool ready);

  rclcpp::Node::SharedPtr node_;
  std::shared_ptr<Inbox> inbox_ = std::make_shared<Inbox>();
  std::map<std::string, rclcpp::Subscription<std_msgs::msg::String>::SharedPtr> subscriptions_;
  std::map<std::string, Source> sources_;
  QJsonObject selected_;
  QString namespace_;
  QString identity_;
  QComboBox * lights_;
  QLabel * status_;
  QLabel * telemetry_;
  QWidget * controls_;
  QWidget * stack_;
  QPushButton * colour_button_;
  QSpinBox * brightness_;
  QSpinBox * base_;
  std::array<QComboBox *, 4> modes_;
  std::array<QComboBox *, 4> rates_;
  QTimer * timer_;
  QColor colour_{Qt::red};
  std::optional<QColor> pending_colour_;
  rclcpp::Publisher<std_msgs::msg::ColorRGBA>::SharedPtr colour_pub_;
  rclcpp::Subscription<std_msgs::msg::String>::SharedPtr status_sub_;
  Clock::time_point status_seen_{};
  rclcpp::Client<Command>::SharedPtr client_;
  std::optional<rclcpp::Client<Command>::FutureAndRequestId> future_;
  Clock::time_point deadline_;
  Clock::time_point next_scan_{};
};
}  // namespace axiom_light_panel
#endif
