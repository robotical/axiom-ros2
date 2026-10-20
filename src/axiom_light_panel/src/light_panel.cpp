// Copyright 2026 Robotical. SPDX-License-Identifier: MIT
#include "axiom_light_panel/light_panel.hpp"
#include <algorithm>
#include <QColorDialog>
#include <QComboBox>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QPushButton>
#include <QSignalBlocker>
#include <QSpinBox>
#include <QTimer>
#include <QVBoxLayout>
#include <rviz_common/display_context.hpp>
#include <rviz_common/ros_integration/ros_node_abstraction_iface.hpp>
#include <pluginlib/class_list_macros.hpp>

namespace axiom_light_panel
{
LightPanel::LightPanel(QWidget * parent) : rviz_common::Panel(parent)
{
  auto layout = new QVBoxLayout(this);
  auto title = new QLabel("<b>Axiom lighting</b>");
  title->setStyleSheet("color: #008ca8; font-size: 18px;");
  layout->addWidget(title);
  lights_ = new QComboBox(this);
  lights_->setObjectName("lights");
  layout->addWidget(lights_);
  status_ = new QLabel("Waiting for live Axiom device inventory", this);
  status_->setObjectName("status");
  status_->setWordWrap(true);
  layout->addWidget(status_);
  telemetry_ = new QLabel("Module status unknown", this);
  telemetry_->setObjectName("module_status");
  telemetry_->setWordWrap(true);
  layout->addWidget(telemetry_);
  controls_ = new QWidget(this);
  auto controls_layout = new QVBoxLayout(controls_);
  controls_layout->setContentsMargins(0, 0, 0, 0);
  auto solid = new QGroupBox("Solid colour", controls_);
  auto solid_layout = new QHBoxLayout(solid);
  colour_button_ = new QPushButton("Choose colour…", solid);
  colour_button_->setObjectName("choose_colour");
  auto apply = new QPushButton("Apply colour", solid);
  apply->setObjectName("apply_colour");
  solid_layout->addWidget(colour_button_);
  solid_layout->addWidget(apply);
  controls_layout->addWidget(solid);
  auto brightness_box = new QGroupBox("Brightness", controls_);
  auto brightness_layout = new QHBoxLayout(brightness_box);
  brightness_ = new QSpinBox(brightness_box);
  brightness_->setObjectName("brightness");
  brightness_->setRange(0, 255);
  brightness_->setValue(64);
  auto brightness_apply = new QPushButton("Apply brightness", brightness_box);
  brightness_apply->setObjectName("apply_brightness");
  brightness_layout->addWidget(brightness_);
  brightness_layout->addWidget(brightness_apply);
  controls_layout->addWidget(brightness_box);
  stack_ = new QGroupBox("Four-tier stack light", controls_);
  auto stack_layout = new QFormLayout(stack_);
  base_ = new QSpinBox(stack_);
  base_->setObjectName("base_period");
  base_->setRange(40, 65535);
  base_->setValue(250);
  base_->setSuffix(" ms");
  stack_layout->addRow("Fastest flash period", base_);
  const QStringList names{"Red (top)", "Amber", "Green", "Blue (bottom)"};
  for (int i = 0; i < 4; ++i) {
    auto row = new QWidget(stack_);
    auto line = new QHBoxLayout(row);
    line->setContentsMargins(0, 0, 0, 0);
    modes_[i] = new QComboBox(row);
    modes_[i]->setObjectName(QString("mode_%1").arg(i));
    modes_[i]->addItems({"Off", "Steady", "Flash", "Opposite phase"});
    rates_[i] = new QComboBox(row);
    rates_[i]->setObjectName(QString("rate_%1").arg(i));
    rates_[i]->addItems({"Period ×1", "Period ×2", "Period ×4", "Period ×8"});
    line->addWidget(modes_[i]);
    line->addWidget(rates_[i]);
    stack_layout->addRow(names[i], row);
  }
  auto stack_apply = new QPushButton("Apply stack pattern", stack_);
  stack_apply->setObjectName("apply_stack");
  stack_layout->addRow(stack_apply);
  controls_layout->addWidget(stack_);
  auto off = new QPushButton("Off — stop pattern and clear LEDs", controls_);
  off->setObjectName("off");
  controls_layout->addWidget(off);
  layout->addWidget(controls_);
  auto note = new QLabel(
    "Controls show requested settings, not measured LED output. "
    "Each tier's period is its multiplier × the base period. "
    "Colour and Off stop flashing; brightness preserves it.", this);
  note->setWordWrap(true);
  layout->addWidget(note);
  layout->addStretch();
  controls(false);
  connect(lights_, QOverload<int>::of(&QComboBox::currentIndexChanged), this,
    [this](int) {selectLight();});
  connect(colour_button_, &QPushButton::clicked, this, &LightPanel::chooseColour);
  connect(apply, &QPushButton::clicked, this, [this]() {requestColour(colour_);});
  connect(brightness_apply, &QPushButton::clicked, this,
    [this]() {sendCommand(service("brightness"), {double(brightness_->value())});});
  connect(off, &QPushButton::clicked, this, [this]() {sendCommand(service("off"), {});});
  connect(stack_apply, &QPushButton::clicked, this, [this]() {
      std::vector<double> values{double(base_->value())};
      // The descriptor/wire order is bottom first; the UI is top first.
      for (int i = 3; i >= 0; --i) {
        values.push_back(modes_[i]->currentIndex() | (rates_[i]->currentIndex() << 2));
      }
      sendCommand(service("stacklight"), values);
    });
  timer_ = new QTimer(this);
  timer_->setInterval(50);
  connect(timer_, &QTimer::timeout, this, &LightPanel::tick);
}

LightPanel::~LightPanel()
{
  timer_->stop();
  if (future_ && client_) {client_->remove_pending_request(*future_);}
}

void LightPanel::onInitialize()
{
  auto abstraction = getDisplayContext()->getRosNodeAbstraction().lock();
  if (abstraction) {setRosNode(abstraction->get_raw_node());}
}

void LightPanel::setRosNode(rclcpp::Node::SharedPtr node)
{
  node_ = std::move(node);
  timer_->start();
}

QString LightPanel::resolve(const QString & path) const
{
  return path.startsWith('/') ? path : namespace_ + '/' + path;
}

QString LightPanel::service(const QString & name) const
{
  for (const auto & entry : selected_["commands"].toArray()) {
    auto command = entry.toObject();
    if (command["name"].toString() == name) {
      return resolve(command["service"].toString());
    }
  }
  return {};
}

void LightPanel::controls(bool ready)
{
  controls_->setEnabled(ready && !future_);
  stack_->setVisible(!service("stacklight").isEmpty());
}

void LightPanel::refreshLights()
{
  QSignalBlocker blocker(lights_);
  const auto previous = lights_->currentData().toJsonObject()["identity"].toString();
  lights_->clear();
  for (const auto & item : sources_) {
    if (Clock::now() - item.second.seen > std::chrono::seconds(5)) {continue;}
    for (auto it = item.second.devices.begin(); it != item.second.devices.end(); ++it) {
      auto device = it.value().toObject();
      if (!device["online"].toBool() || device["stale"].toBool() ||
        !device["metadata_ready"].toBool()) {continue;}
      QString colour_topic;
      for (const auto & entry : device["command_topics"].toArray()) {
        auto command = entry.toObject();
        if (command["kind"].toString() == "colour" && !command.contains("pixel")) {
          colour_topic = command["topic"].toString();
        }
      }
      if (colour_topic.isEmpty()) {continue;}
      auto root = QString::fromStdString(item.first);
      root = root.left(root.lastIndexOf('/'));
      device["root"] = root;
      device["colour_topic"] = colour_topic;
      device["identity"] = root + '/' + device["topic"].toString() + ':' +
        QString::number(device["revision"].toInt());
      lights_->addItem(root + '/' + device["topic"].toString(), device);
    }
  }
  int selected = -1;
  for (int i = 0; i < lights_->count(); ++i) {
    if (lights_->itemData(i).toJsonObject()["identity"].toString() == previous) {selected = i;}
  }
  lights_->setCurrentIndex(selected < 0 && lights_->count() ? 0 : selected);
  selectLight();
}

void LightPanel::selectLight()
{
  const auto selected = lights_->currentData().toJsonObject();
  const auto identity = selected["identity"].toString();
  if (identity != identity_) {
    pending_colour_.reset();
    if (future_ && client_) {client_->remove_pending_request(*future_);}
    future_.reset();
    client_.reset();
    colour_pub_.reset();
    status_sub_.reset();
    telemetry_->setText("Module status unknown");
    status_seen_ = {};
    identity_ = identity;
    selected_ = selected;
    namespace_ = selected["root"].toString();
    if (!identity.isEmpty()) {
      colour_pub_ = node_->create_publisher<std_msgs::msg::ColorRGBA>(
        resolve(selected["colour_topic"].toString()).toStdString(), rclcpp::QoS(1).reliable());
      auto inbox = inbox_;
      const auto tag = identity.toStdString() + "|data";
      status_sub_ = node_->create_subscription<std_msgs::msg::String>(
        resolve(selected["topic"].toString() + "/data").toStdString(),
        rclcpp::QoS(1).best_effort(),
        [inbox, tag](std_msgs::msg::String::ConstSharedPtr message) {
          std::lock_guard<std::mutex> lock(inbox->mutex);
          inbox->events.push_back({tag, message->data});
        });
    }
    status_->setText(identity.isEmpty() ? "No live supported light. Waiting for inventory." :
      "Light discovered. No output sent; choose a control to begin.");
  }
  controls(colour_pub_ && colour_pub_->get_subscription_count() > 0);
}

void LightPanel::chooseColour()
{
  auto dialog = new QColorDialog(colour_, this);
  dialog->setAttribute(Qt::WA_DeleteOnClose);
  dialog->setOption(QColorDialog::DontUseNativeDialog);
  const auto identity = identity_;
  connect(dialog, &QColorDialog::currentColorChanged, this,
    [this, identity](const QColor & colour) {
      if (identity == identity_ && controls_->isEnabled()) {requestColour(colour);}
    });
  dialog->open();
}

void LightPanel::requestColour(const QColor & colour)
{
  if (!controls_->isEnabled() || !colour.isValid()) {return;}
  colour_ = colour;
  colour_button_->setStyleSheet("background-color: " + colour.name() + ';');
  pending_colour_ = colour;
}

void LightPanel::sendCommand(const QString & path, const std::vector<double> & values)
{
  if (!controls_->isEnabled() || path.isEmpty()) {return;}
  pending_colour_.reset();
  client_ = node_->create_client<Command>(path.toStdString());
  if (!client_->service_is_ready()) {
    status_->setText("Command service unavailable; no request sent.");
    return;
  }
  auto request = std::make_shared<Command::Request>();
  request->values = values;
  future_ = client_->async_send_request(request);
  deadline_ = Clock::now() + std::chrono::seconds(5);
  status_->setText("Waiting for driver acknowledgement…");
  controls(false);
}

void LightPanel::tick()
{
  if (!node_) {return;}
  if (Clock::now() >= next_scan_) {
    next_scan_ = Clock::now() + std::chrono::seconds(1);
    for (const auto & [topic, types] : node_->get_topic_names_and_types()) {
      if (topic.size() < 8 || topic.substr(topic.size() - 8) != "/devices" ||
        std::find(types.begin(), types.end(), "std_msgs/msg/String") == types.end() ||
        subscriptions_.count(topic)) {continue;}
      auto inbox = inbox_;
      subscriptions_[topic] = node_->create_subscription<std_msgs::msg::String>(
        topic, rclcpp::QoS(1).reliable().transient_local(),
        [inbox, topic](std_msgs::msg::String::ConstSharedPtr message) {
          std::lock_guard<std::mutex> lock(inbox->mutex);
          inbox->events.push_back({topic, message->data});
        });
    }
  }
  std::deque<Event> events;
  {std::lock_guard<std::mutex> lock(inbox_->mutex); events.swap(inbox_->events);}
  for (const auto & event : events) {
    const auto doc = QJsonDocument::fromJson(QByteArray::fromStdString(event.json));
    if (event.topic == identity_.toStdString() + "|data" && doc.isObject()) {
      const auto values = doc.object()["values"].toObject();
      auto value = [&values](const QString & name) {
          const auto entry = values[name].toObject();
          return entry["valid"].toBool() && entry["value"].isDouble() ?
            QString::number(entry["value"].toDouble()) : QString("unknown");
        };
      telemetry_->setText(QString("Module: flags %1 · commands %2 · errors %3 · "
        "last error %4 · brightness %5")
        .arg(value("flags"), value("cmdCount"), value("errCount"),
        value("lastError"), value("brightness")));
      status_seen_ = Clock::now();
      continue;
    }
    if (!doc.isArray()) {continue;}
    QJsonObject devices;
    for (const auto & entry : doc.array()) {
      auto device = entry.toObject();
      devices[device["topic"].toString()] = device;
    }
    sources_[event.topic] = {devices, Clock::now()};
    // Preserve removal/replacement events even when a reconnect is very fast.
    refreshLights();
  }
  refreshLights();
  if (Clock::now() - status_seen_ > std::chrono::seconds(5)) {
    telemetry_->setText("Module status unknown or stale");
  }
  if (future_) {
    if (future_->wait_for(std::chrono::seconds(0)) == std::future_status::ready) {
      try {
        const auto response = future_->get();
        status_->setText(response->success ?
          "Driver acknowledged the request (not physical output confirmation)." :
          "Driver rejected request: " + QString::fromStdString(response->message));
      } catch (const std::exception & error) {
        status_->setText("Command failed: " + QString::fromUtf8(error.what()));
      }
      future_.reset();
    } else if (Clock::now() >= deadline_) {
      client_->remove_pending_request(*future_);
      future_.reset();
      status_->setText("Command timed out; output state unknown. No automatic retry.");
    }
    controls(colour_pub_ && colour_pub_->get_subscription_count() > 0);
  }
  if (pending_colour_) {
    const auto colour = *pending_colour_;
    pending_colour_.reset();
    if (controls_->isEnabled()) {
      std_msgs::msg::ColorRGBA message;
      message.r = colour.redF(); message.g = colour.greenF(); message.b = colour.blueF();
      message.a = 1.0;
      colour_pub_->publish(message);
      status_->setText("Colour target published; check device status for hardware errors.");
    }
  }
}
}  // namespace axiom_light_panel
PLUGINLIB_EXPORT_CLASS(axiom_light_panel::LightPanel, rviz_common::Panel)
