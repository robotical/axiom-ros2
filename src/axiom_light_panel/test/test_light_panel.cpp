// Copyright 2026 Robotical. SPDX-License-Identifier: MIT
#include <gtest/gtest.h>
#include <QApplication>
#include <QColorDialog>
#include <QComboBox>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QPushButton>
#include <QSpinBox>
#include <QTest>
#include <QTimer>
#include <thread>
#include "axiom_light_panel/light_panel.hpp"

namespace
{
using Command = axiom_interfaces::srv::DeviceCommand;
class PanelTest : public testing::Test
{
protected:
  void SetUp() override
  {
    node = std::make_shared<rclcpp::Node>("light_panel_test");
    panel = std::make_unique<axiom_light_panel::LightPanel>();
    panel->setRosNode(node);
    panel->resize(620, 700);
    panel->show();
    peer = std::make_shared<rclcpp::Node>("light_mock");
    inventory = peer->create_publisher<std_msgs::msg::String>(
      "/test_board/devices", rclcpp::QoS(1).transient_local());
    colour = peer->create_subscription<std_msgs::msg::ColorRGBA>(
      "/test_board/light/commands/colour", 1,
      [this](std_msgs::msg::ColorRGBA::ConstSharedPtr value) {colours.push_back(*value);});
    for (const std::string name : {"brightness", "off", "stacklight"}) {
      services.push_back(peer->create_service<Command>("/test_board/light/commands/" + name,
        [this, name](std::shared_ptr<Command::Request> request,
        std::shared_ptr<Command::Response> response) {
          calls.emplace_back(name, request->values);
          response->success = !reject;
          response->message = reject ? "Test rejection" : "ok";
        }));
    }
    executor.add_node(node);
    executor.add_node(peer);
    // Both ROS callbacks and widgets run on this test thread, matching RViz's Qt loop.
    spin = new QTimer(panel.get());
    QObject::connect(spin, &QTimer::timeout, panel.get(), [this]() {executor.spin_some();});
    spin->start(5);
  }
  void TearDown() override
  {
    spin->stop();
    executor.remove_node(node); executor.remove_node(peer);
    panel.reset(); node.reset(); peer.reset();
  }
  template<typename Predicate> void wait(Predicate predicate, int ms = 4000)
  {
    for (int elapsed = 0; elapsed < ms && !predicate(); elapsed += 20) {QTest::qWait(20);}
    ASSERT_TRUE(predicate());
  }
  void announce(bool online = true, int revision = 1)
  {
    QJsonArray commands;
    for (const auto & name : {"brightness", "off", "stacklight"}) {
      commands.append(QJsonObject{{"name", name}, {"service", QString("light/commands/") + name}});
    }
    const QJsonObject light{{"online", online}, {"stale", false}, {"metadata_ready", true},
      {"revision", revision}, {"topic", "light"}, {"commands", commands},
      {"command_topics", QJsonArray{QJsonObject{{"kind", "colour"},
        {"topic", "light/commands/colour"}}}}};
    inventory->publish(std_msgs::msg::String().set__data(
      QJsonDocument(QJsonArray{light}).toJson().toStdString()));
  }
  QPushButton * button(const char * name) {return panel->findChild<QPushButton *>(name);}
  std::unique_ptr<axiom_light_panel::LightPanel> panel;
  rclcpp::Node::SharedPtr node, peer;
  rclcpp::executors::SingleThreadedExecutor executor;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr inventory;
  rclcpp::Subscription<std_msgs::msg::ColorRGBA>::SharedPtr colour;
  std::vector<rclcpp::Service<Command>::SharedPtr> services;
  std::vector<std_msgs::msg::ColorRGBA> colours;
  std::vector<std::pair<std::string, std::vector<double>>> calls;
  QTimer * spin;
  bool reject = false;
};

TEST_F(PanelTest, DiscoveryColourStackBrightnessOffAndNoReconnectReplay)
{
  EXPECT_FALSE(button("apply_colour")->isEnabled());
  announce();
  wait([this]() {return button("apply_colour")->isEnabled();});
  EXPECT_TRUE(calls.empty()); EXPECT_TRUE(colours.empty());
  QTest::mouseClick(button("apply_colour"), Qt::LeftButton);
  wait([this]() {return colours.size() == 1;});
  EXPECT_FLOAT_EQ(colours[0].r, 1.0);
  panel->findChild<QComboBox *>("mode_0")->setCurrentIndex(3);
  panel->findChild<QComboBox *>("rate_0")->setCurrentIndex(2);
  panel->findChild<QComboBox *>("mode_3")->setCurrentIndex(2);
  QTest::mouseClick(button("apply_stack"), Qt::LeftButton);
  wait([this]() {return calls.size() == 1 && button("off")->isEnabled();});
  EXPECT_EQ(calls[0].first, "stacklight");
  EXPECT_EQ(calls[0].second, (std::vector<double>{250, 2, 0, 0, 11}));
  panel->findChild<QSpinBox *>("brightness")->setValue(32);
  QTest::mouseClick(button("apply_brightness"), Qt::LeftButton);
  wait([this]() {return calls.size() == 2 && button("off")->isEnabled();});
  EXPECT_EQ(calls[1].second, (std::vector<double>{32}));
  QTest::mouseClick(button("off"), Qt::LeftButton);
  wait([this]() {return calls.size() == 3 && button("off")->isEnabled();});
  announce(false);
  wait([this]() {return !button("apply_colour")->isEnabled();});
  announce(true, 2);
  wait([this]() {return button("apply_colour")->isEnabled();});
  QTest::qWait(150);
  EXPECT_EQ(colours.size(), 1U); EXPECT_EQ(calls.size(), 3U);
  QTest::mouseClick(button("apply_colour"), Qt::LeftButton);
  wait([this]() {return colours.size() == 2;});
}

TEST_F(PanelTest, ColourPickerCoalescesAndServiceFailureIsVisible)
{
  announce();
  wait([this]() {return button("choose_colour")->isEnabled();});
  QTest::mouseClick(button("choose_colour"), Qt::LeftButton);
  auto dialog = panel->findChild<QColorDialog *>();
  ASSERT_NE(dialog, nullptr);
  for (int i = 1; i <= 200; ++i) {dialog->setCurrentColor(QColor(i, 20, 30));}
  wait([this]() {return colours.size() == 1;});
  EXPECT_NEAR(colours[0].r, 200. / 255, 1e-6);
  dialog->close();
  reject = true;
  QTest::mouseClick(button("off"), Qt::LeftButton);
  wait([this]() {return panel->findChild<QLabel *>("status")->text().contains("Test rejection");});
  EXPECT_TRUE(button("apply_colour")->isEnabled());
}

TEST_F(PanelTest, StaleInventoryDisablesControlsWithoutReplayingOutput)
{
  announce();
  wait([this]() {return button("apply_colour")->isEnabled();});
  wait([this]() {return !button("apply_colour")->isEnabled();}, 6000);
  EXPECT_TRUE(calls.empty()); EXPECT_TRUE(colours.empty());
  announce();
  wait([this]() {return button("apply_colour")->isEnabled();});
  EXPECT_TRUE(calls.empty()); EXPECT_TRUE(colours.empty());
}

TEST_F(PanelTest, TimedOutServiceLeavesQtResponsiveAndDoesNotRetry)
{
  services[1].reset();
  services[1] = peer->create_service<Command>("/test_board/light/commands/off",
    [this](std::shared_ptr<rmw_request_id_t>, std::shared_ptr<Command::Request> request) {
      calls.emplace_back("off", request->values);  // Deliberately defer the response forever.
    });
  QTimer heartbeat;
  QObject::connect(&heartbeat, &QTimer::timeout, panel.get(), [this]() {announce();});
  heartbeat.start(300);
  announce();
  wait([this]() {return button("off")->isEnabled();});
  QTest::mouseClick(button("off"), Qt::LeftButton);
  wait([this]() {return panel->findChild<QLabel *>("status")->text().contains("timed out");},
    6000);
  EXPECT_TRUE(button("apply_colour")->isEnabled());
  EXPECT_EQ(calls.size(), 1U);
}
}  // namespace

int main(int argc, char ** argv)
{
  QApplication app(argc, argv);
  rclcpp::init(argc, argv);
  testing::InitGoogleTest(&argc, argv);
  const int result = RUN_ALL_TESTS();
  rclcpp::shutdown();
  return result;
}
