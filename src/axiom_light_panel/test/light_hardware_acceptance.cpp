// Copyright 2026 Robotical. SPDX-License-Identifier: MIT
// Manual integration test; AXIOM_LIGHT_HARDWARE=1 is required. Not run by CTest.
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <QApplication>
#include <QColorDialog>
#include <QComboBox>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QPushButton>
#include <QSpinBox>
#include <QTest>
#include <QTimer>
#include <rviz_common/visualization_frame.hpp>
#include <rviz_common/ros_integration/ros_node_abstraction.hpp>
#include <axiom_interfaces/srv/ric_rest_url.hpp>
#include <axiom_interfaces/srv/connect.hpp>
#include <axiom_interfaces/srv/disconnect.hpp>
#include "axiom_light_panel/light_panel.hpp"

namespace
{
void require(bool success, const char * message)
{
  if (!success) {throw std::runtime_error(message);}
}
template<typename Predicate> void wait(Predicate predicate, int ms = 7000)
{
  for (int elapsed = 0; elapsed < ms && !predicate(); elapsed += 20) {QTest::qWait(20);}
  require(predicate(), "GUI acceptance timed out");
}
}  // namespace

int main(int argc, char ** argv)
{
  if (!std::getenv("AXIOM_LIGHT_HARDWARE") ||
    std::string(std::getenv("AXIOM_LIGHT_HARDWARE")) != "1" || argc != 3)
  {
    std::cerr << "Requires AXIOM_LIGHT_HARDWARE=1, layout path and evidence directory\n";
    return 2;
  }
  QApplication app(argc, argv);
  rclcpp::init(argc, argv);
  int result = 0;
  {
    auto abstraction = std::make_shared<rviz_common::ros_integration::RosNodeAbstraction>(
      "lighting_rviz_acceptance");
    rviz_common::VisualizationFrame frame(abstraction);
    frame.setApp(&app);
    frame.setSplashPath("");
    frame.initialize(abstraction, argv[1]);
    frame.resize(1160, 850);
    frame.show();
    auto panel = frame.findChild<axiom_light_panel::LightPanel *>();
    require(panel, "Saved RViz layout did not load the lighting plugin");
    auto button = [panel](const char * name) {return panel->findChild<QPushButton *>(name);};
    auto probe = std::make_shared<rclcpp::Node>("lighting_gui_readback");
    auto spin = new QTimer(&frame);
    QObject::connect(spin, &QTimer::timeout, &frame, [probe]() {rclcpp::spin_some(probe);});
    spin->start(5);
    QJsonObject report;
    QJsonArray steps;
    std::string device, ns;
    auto rpc = [&](const std::string & write, int size) {
        auto client = probe->create_client<axiom_interfaces::srv::RicRestUrl>(ns + "/ric_rest_url");
        require(client->wait_for_service(std::chrono::seconds(3)), "ROS readback service missing");
        auto request = std::make_shared<axiom_interfaces::srv::RicRestUrl::Request>();
        request->url_path = "devman/cmdraw?deviceid=" + device + "&hexWr=" + write +
          "&numToRd=" + std::to_string(size);
        request->timeout = 4.0;
        auto future = client->async_send_request(request);
        wait([&]() {return future.wait_for(std::chrono::seconds(0)) == std::future_status::ready;});
        auto response = future.get();
        require(response->success, "Readback service rejected request");
        auto json = QJsonDocument::fromJson(QByteArray::fromStdString(response->json_text)).object();
        auto bytes = QByteArray::fromHex(json["rdData"].toString().toLatin1());
        require(bytes.size() == size, "Readback length incorrect");
        uint16_t crc = 0xffff;
        for (int i = 0; i < bytes.size() - 2; ++i) {
          crc ^= uint16_t(uint8_t(bytes[i])) << 8;
          for (int bit = 0; bit < 8; ++bit) {
            crc = crc & 0x8000 ? uint16_t((crc << 1) ^ 0x1021) : uint16_t(crc << 1);
          }
        }
        require(crc == (uint16_t(uint8_t(bytes[size - 2])) << 8 | uint8_t(bytes[size - 1])),
          "Module readback CRC failed");
        return bytes.left(size - 3);
      };
    auto click = [&](const char * name) {
        wait([&]() {return button(name)->isEnabled();});
        QTest::mouseClick(button(name), Qt::LeftButton);
        QTest::qWait(250);
        wait([&]() {return button("off")->isEnabled();});
      };
    try {
      wait([&]() {return button("apply_colour")->isEnabled();});
      const auto selected = panel->findChild<QComboBox *>("lights")->currentData().toJsonObject();
      ns = selected["root"].toString().toStdString();
      device = (selected["bus"].toString() + '_' + selected["address"].toString()).toStdString();
      report["selected"] = selected["identity"];
      auto before = rpc("20", 11);
      QTest::qWait(1100);
      require(rpc("20", 11)[2] == before[2], "Opening RViz sent an output command");
      report["startup_no_write"] = true;
      const auto errors = uint8_t(before[3]);
      const auto brightness = uint8_t(before[7]);
      for (const auto & colour : {QColor(Qt::red), QColor(Qt::green), QColor(Qt::blue),
          QColor(18, 52, 86)})
      {
        click("choose_colour");
        auto dialog = panel->findChild<QColorDialog *>();
        require(dialog, "Colour picker failed to open");
        dialog->setCurrentColor(colour);
        QTest::qWait(150);
        dialog->accept();
        click("apply_colour");
        for (const auto [start, count] : {std::pair<int, int>{0, 24}, {24, 8}}) {
          QByteArray bytes;
          bytes.append(char(0x23)); bytes.append(char(start)); bytes.append(char(count));
          const auto data = rpc(bytes.toHex().toStdString(), 1 + count * 3 + 3);
          for (int i = 0; i < count; ++i) {
            require(uint8_t(data[1+i*3]) == colour.red() &&
              uint8_t(data[2+i*3]) == colour.green() &&
              uint8_t(data[3+i*3]) == colour.blue(), "GUI colour did not reach every LED");
          }
        }
        steps.append("GUI colour " + colour.name() + ": all 32 pixels CRC-verified");
      }
      for (int i = 0; i < 4; ++i) {
        panel->findChild<QComboBox *>(QString("mode_%1").arg(i))->setCurrentIndex(i % 2 ? 2 : 3);
      }
      click("apply_stack");
      auto pattern = rpc("24", 15);
      require(pattern.left(8).toHex() == "0100fa0402030203", "GUI stack tier order incorrect");
      require(uint8_t(rpc("20", 11)[1]) & 4, "GUI stack did not start");
      steps.append("GUI stack: state and running flag CRC-verified");
      panel->findChild<QSpinBox *>("brightness")->setValue(32);
      click("apply_brightness");
      auto state = rpc("20", 11);
      require(uint8_t(state[7]) == 32 && (uint8_t(state[1]) & 4),
        "GUI brightness failed or stopped the pattern");
      QDir().mkpath(argv[2]);
      QTest::qWait(1200);
      frame.grab().save(QString(argv[2]) + "/rviz-stack.png");
      click("apply_colour");
      require(!(uint8_t(rpc("20", 11)[1]) & 4), "Returning colour did not stop stack");
      click("apply_stack");
      click("off");
      require(!(uint8_t(rpc("20", 11)[1]) & 4), "GUI Off did not stop stack");
      click("apply_colour");
      auto data = rpc("230001", 7);
      require(data.toHex() == "01123456", "Same colour after Off was suppressed");
      steps.append("GUI same-colour return after stack and Off verified");
      const auto count_before_reconnect = uint8_t(rpc("20", 11)[2]);
      auto disconnect = probe->create_client<axiom_interfaces::srv::Disconnect>(ns + "/disconnect");
      require(disconnect->wait_for_service(std::chrono::seconds(3)), "Disconnect service missing");
      auto disconnected = disconnect->async_send_request(
        std::make_shared<axiom_interfaces::srv::Disconnect::Request>());
      wait([&]() {
          return disconnected.wait_for(std::chrono::seconds(0)) == std::future_status::ready;
        });
      require(disconnected.get()->success, "Driver disconnect failed");
      wait([&]() {return !button("apply_colour")->isEnabled();});
      auto connect = probe->create_client<axiom_interfaces::srv::Connect>(ns + "/connect");
      require(connect->wait_for_service(std::chrono::seconds(3)), "Connect service missing");
      auto connected = connect->async_send_request(
        std::make_shared<axiom_interfaces::srv::Connect::Request>());
      wait([&]() {return connected.wait_for(std::chrono::seconds(0)) == std::future_status::ready;});
      require(connected.get()->success, "Driver reconnect failed");
      wait([&]() {return button("apply_colour")->isEnabled();});
      QTest::qWait(400);
      require(uint8_t(rpc("20", 11).at(2)) == count_before_reconnect,
        "Panel replayed output on reconnect");
      click("apply_colour");
      require(uint8_t(rpc("20", 11)[2]) == uint8_t(uint8_t(count_before_reconnect) + 1),
        "Fresh GUI colour after reconnect was not sent");
      steps.append("GUI transport disconnect disables controls; reconnect sends no cached output");
      click("off");
      panel->findChild<QSpinBox *>("brightness")->setValue(brightness);
      click("apply_brightness");
      const auto after = rpc("20", 11);
      require(uint8_t(after.at(3)) == errors && after.at(4) == 0,
        "Module rejected a GUI command");
      for (const auto [start, count] : {std::pair<int, int>{0, 24}, {24, 8}}) {
        QByteArray bytes;
        bytes.append(char(0x23)); bytes.append(char(start)); bytes.append(char(count));
        const auto pixels = rpc(bytes.toHex().toStdString(), 1 + count * 3 + 3);
        require(pixels.mid(1) == QByteArray(count * 3, '\0'), "GUI Off left LEDs lit");
      }
      report["final_status_hex"] = QString(after.toHex());
      QTest::qWait(1200);
      frame.grab().save(QString(argv[2]) + "/rviz-off.png");
      report["steps"] = steps;
      report["module_feedback"] = panel->findChild<QLabel *>("module_status")->text();
      QFile file(QString(argv[2]) + "/gui-result.json");
      require(file.open(QIODevice::WriteOnly), "Cannot save GUI evidence");
      file.write(QJsonDocument(report).toJson());
      std::cout << QJsonDocument(report).toJson().toStdString();
    } catch (const std::exception & error) {
      std::cerr << error.what() << '\n';
      result = 1;
      // Best-effort normal ROS control cleanup, never a raw output write.
      if (button("off")->isEnabled()) {click("off");}
    }
    spin->stop();
    frame.hide();
  }
  rclcpp::shutdown();
  return result;
}
