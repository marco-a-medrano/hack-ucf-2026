

#include <WiFi.h>
#include <WebServer.h>

const char* ssid = "Jeremy’s iPhone";
const char* password = "password";

const int STEERING = 17;
const int THROTTLE = 18;

WebServer server(80);

// ===== SQUARE ROUTE SETTINGS =====

// Straight duration for each side in milliseconds
const unsigned long SIDE_TIME[4] = {
  3000,  // Side 1
  3000,  // Side 2
  3000,  // Side 3
  3000   // Side 4
};

// Turning duration for each corner
const unsigned long TURN_TIME[4] = {
  2225,  // Corner 1
  2225,  // Corner 2
  2225,  // Corner 3
  2225   // Corner 4
};

const int DRIVE_THROTTLE = 1550;
const int TURN_THROTTLE = 1550;
const int TURN_STEERING = 1200;

// ===== STEERING CORRECTION =====

const int STEERING_CENTER = 1500;
const int LEFT_TURN_CORRECTION = 1610;
const int RIGHT_TURN_CORRECTION = 1400;
const unsigned long CORRECTION_TIME = 350;

// Maximum route time
const unsigned long MAX_ROUTE_TIME = 25000;

// ===== STATE =====

bool driving = false;
bool turned = false;

unsigned long driveStart = 0;
unsigned long turnStart = 0;

enum RoutePhase {
  IDLE,
  STRAIGHT,
  CORNER,
  CORRECTION
};

RoutePhase routePhase = IDLE;

bool squareRunning = false;
int squareResult = 0;
int segment = 0;

unsigned long phaseStart = 0;
unsigned long routeStart = 0;

String routeState = "Idle";

// ===== WIFI =====

unsigned long lastReconnect = 0;
const unsigned long RECONNECT_INTERVAL = 5000;

bool wasConnected = false;

// ===== WEB PAGE =====

const char PAGE[] PROGMEM = R"HTML(
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>RC Controller</title>

<style>
body {
  background:#111827;
  color:white;
  font-family:Arial,sans-serif;
  text-align:center;
  padding:30px 15px;
}

main {
  max-width:540px;
  margin:auto;
}

button {
  padding:22px;
  margin:8px;
  border:0;
  border-radius:12px;
  font-size:20px;
  background:#2563eb;
  color:white;
  cursor:pointer;
}

button:disabled {
  opacity:.55;
}

.motor {
  background:#15803d;
  width:90%;
}

.square {
  background:#059669;
  width:90%;
}

.stop {
  background:#dc2626;
  width:90%;
}

p {
  color:#cbd5e1;
  line-height:1.5;
}

.panel {
  background:#1f2937;
  border-radius:14px;
  margin-top:20px;
  padding:22px;
}

.value {
  font-size:52px;
  font-weight:bold;
  color:#f87171;
}

.value.complete {
  color:#4ade80;
}

#status {
  min-height:48px;
}
</style>
</head>

<body>
<main>

<h1>RC Controller</h1>
<p>ESP32-S3 Autonomous Rover</p>

<div>
<button onclick="send('l')">Left</button>
<button onclick="send('c')">Center</button>
<button onclick="send('r')">Right</button>
</div>

<button class="motor" id="motor"
onclick="motorTest()">
Forward test · 1 second
</button>

<button class="square" id="squareButton"
onclick="startSquare()">
AUTONOMOUS SQUARE
</button>

<button class="stop" onclick="send('x')">
STOP / NEUTRAL
</button>

<p id="status" role="status">
Ready to send a command
</p>

<div class="panel">

<h2>Rover Feedback</h2>

<div id="result" class="value">0</div>

<p id="resultText">
Waiting for operation
</p>

<p id="routeState">
Route: Idle
</p>

<p id="connection">
Checking connection...
</p>

</div>

<p>
0 = Not completed<br>
1 = Square route completed
</p>

<p>
Autonomous route continues without Wi-Fi.<br>
STOP requires an active connection.
</p>

</main>

<script>

async function send(command) {
  try {
    const response = await fetch(
      '/command?c=' + command,
      {
        method:'POST',
        cache:'no-store',
        signal:AbortSignal.timeout(2500)
      }
    );

    const message = await response.text();

    if (!response.ok) {
      throw new Error(message);
    }

    document.getElementById('status')
      .textContent = message;

    return true;

  } catch(error) {
    document.getElementById('status')
      .textContent =
        'Command failed. Check connection.';

    return false;
  }
}

async function motorTest() {
  const button = document.getElementById('motor');

  button.disabled = true;

  await send('f');

  setTimeout(() => {
    button.disabled = false;
  }, 1200);
}

async function startSquare() {
  const button =
    document.getElementById('squareButton');

  button.disabled = true;

  const success = await send('s');

  if (!success) {
    button.disabled = false;
    return;
  }

  button.textContent = 'SQUARE RUNNING...';

  document.getElementById('result')
    .textContent = '0';

  document.getElementById('result')
    .classList.remove('complete');
}

async function updateFeedback() {
  const connection =
    document.getElementById('connection');

  try {
    const response = await fetch('/status', {
      cache:'no-store',
      signal:AbortSignal.timeout(1500)
    });

    if (!response.ok) {
      throw new Error();
    }

    const data = await response.json();

    connection.textContent = 'Wi-Fi: Connected';
    connection.style.color = '#4ade80';

    const result =
      document.getElementById('result');

    const button =
      document.getElementById('squareButton');

    result.textContent = data.result;

    result.classList.toggle(
      'complete',
      data.result === 1
    );

    document.getElementById('resultText')
      .textContent =
      data.result === 1
        ? 'Square route completed'
        : data.running
        ? 'Autonomous route running'
        : 'Waiting for operation';

    document.getElementById('routeState')
      .textContent = 'Route: ' + data.phase;

    button.disabled = data.running;

    button.textContent = data.running
      ? 'SQUARE RUNNING...'
      : 'AUTONOMOUS SQUARE';

  } catch(error) {
    connection.textContent =
      'Wi-Fi: Disconnected';

    connection.style.color = '#f87171';
  }
}

setInterval(updateFeedback, 1000);
updateFeedback();

</script>
</body>
</html>
)HTML";

// ===== MOTOR CONTROL =====

void pulse(int pin, unsigned int microseconds) {
  ledcWrite(
    pin,
    (microseconds * 16384UL + 10000) / 20000
  );
}

void stopAll() {
  pulse(THROTTLE, 1500);
  pulse(STEERING, STEERING_CENTER);

  driving = false;
  turned = false;
  squareRunning = false;
  routePhase = IDLE;
}

void cancelSquare() {
  stopAll();

  squareResult = 0;
  routeState = "Stopped";
}

// ===== AUTONOMOUS NAVIGATION =====

void beginStraight() {
  routePhase = STRAIGHT;
  phaseStart = millis();

  pulse(STEERING, STEERING_CENTER);
  pulse(THROTTLE, DRIVE_THROTTLE);

  routeState =
    "Straight " + String(segment + 1);

  Serial.println(routeState);
}

void beginCorner() {
  routePhase = CORNER;
  phaseStart = millis();

  pulse(STEERING, TURN_STEERING);
  pulse(THROTTLE, TURN_THROTTLE);

  routeState =
    "Corner " + String(segment + 1);

  Serial.println(routeState);
}

// ===== STEERING CORRECTION =====

void beginCorrection() {
  routePhase = CORRECTION;
  phaseStart = millis();

  // Neutral throttle while correcting
  pulse(THROTTLE, 1500);

  // Brief opposite-direction steering pulse
  pulse(STEERING, LEFT_TURN_CORRECTION);

  routeState =
    "Correcting corner " + String(segment + 1);

  Serial.println(routeState);
}

// ===== START SQUARE =====

void startSquare() {
  stopAll();

  squareResult = 0;
  squareRunning = true;
  segment = 0;

  routeStart = millis();

  beginStraight();

  Serial.println("Square route started");
}

// ===== UPDATE SQUARE =====

void updateSquare() {
  if (!squareRunning) return;

  unsigned long now = millis();

  // Safety timeout
  if (now - routeStart >= MAX_ROUTE_TIME) {
    cancelSquare();

    routeState = "Safety timeout";

    Serial.println("Square safety timeout");
    return;
  }

  // Straight driving
  if (routePhase == STRAIGHT &&
      now - phaseStart >= SIDE_TIME[segment]) {

    beginCorner();
  }

  // Turning
  else if (routePhase == CORNER &&
           now - phaseStart >= TURN_TIME[segment]) {

    beginCorrection();
  }

  // Finish correction
  else if (routePhase == CORRECTION &&
           now - phaseStart >= CORRECTION_TIME) {

    // Return steering to center
    pulse(STEERING, STEERING_CENTER);

    segment++;

    if (segment >= 4) {
      stopAll();

      squareResult = 1;
      routeState = "Complete";

      Serial.println(
        "Square complete: result = 1"
      );

    } else {
      beginStraight();
    }
  }
}

// ===== WIFI RECONNECTION =====

void maintainWiFi() {
  bool connected =
    WiFi.status() == WL_CONNECTED;

  if (connected) {
    if (!wasConnected) {
      Serial.println("Wi-Fi reconnected!");
      Serial.println(WiFi.localIP());
    }

    wasConnected = true;
    return;
  }

  if (wasConnected) {
    Serial.println("Wi-Fi lost");
    wasConnected = false;
  }

  if (millis() - lastReconnect >=
      RECONNECT_INTERVAL) {

    lastReconnect = millis();

    WiFi.reconnect();
  }
}

// ===== MANUAL TIMEOUTS =====

void checkTimeouts() {
  if (squareRunning) {
    updateSquare();
    return;
  }

  if (WiFi.status() != WL_CONNECTED) {
    if (driving || turned) {
      stopAll();
    }
    return;
  }

  if (driving &&
      millis() - driveStart >= 1000) {

    pulse(THROTTLE, 1500);
    driving = false;
  }

  if (turned &&
      millis() - turnStart >= 1000) {

    pulse(STEERING, STEERING_CENTER);
    turned = false;
  }
}

// ===== COMMAND HANDLING =====

void handleCommand() {
  checkTimeouts();

  String command = server.arg("c");
  String message;

  // Stop command
  if (command == "x") {
    cancelSquare();

    message =
      "Throttle neutral; steering centered";
  }

  else if (WiFi.status() != WL_CONNECTED) {
    server.send(
      503,
      "text/plain",
      "Wi-Fi disconnected"
    );
    return;
  }

  // Block other commands during square
  else if (squareRunning) {
    server.send(
      409,
      "text/plain",
      "Square running. Press STOP."
    );
    return;
  }

  // Start square route
  else if (command == "s") {
    startSquare();

    message = "Autonomous square started";
  }

  // Existing motor test
  else if (command == "f") {
    if (driving) {
      server.send(
        409,
        "text/plain",
        "Motor already running"
      );
      return;
    }

    driveStart = millis();
    driving = true;

    pulse(THROTTLE, 1550);

    message = "One-second motor test started";
  }

  // Existing steering controls
  else if (
    command == "l" ||
    command == "r" ||
    command == "c"
  ) {
    unsigned int position = STEERING_CENTER;

    if (command == "l") {
      position = 1300;
    }

    if (command == "r") {
      position = 1700;
    }

    pulse(STEERING, position);

    turned = command != "c";
    turnStart = millis();

    message =
      "Steering command received: " + command;
  }

  else {
    server.send(
      400,
      "text/plain",
      "Unknown command"
    );
    return;
  }

  Serial.println(message);

  server.sendHeader(
    "Cache-Control",
    "no-store"
  );

  server.send(
    200,
    "text/plain",
    message
  );
}

// ===== FEEDBACK ENDPOINT =====

void handleStatus() {
  String json = "{";

  json += "\"result\":";
  json += String(squareResult);

  json += ",\"running\":";
  json += (squareRunning ? "true" : "false");

  json += ",\"phase\":\"";
  json += routeState;
  json += "\"}";

  server.sendHeader(
    "Cache-Control",
    "no-store"
  );

  server.send(
    200,
    "application/json",
    json
  );
}

// ===== SETUP =====

void setup() {
  Serial.begin(115200);

  bool steeringOK =
    ledcAttach(STEERING, 50, 14);

  bool throttleOK =
    ledcAttach(THROTTLE, 50, 14);

  if (!steeringOK || !throttleOK) {
    Serial.println("PWM setup failed");

    while (true) {
      delay(1000);
    }
  }

  stopAll();

  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(ssid, password);

  unsigned long connectionStart = millis();

  while (
    WiFi.status() != WL_CONNECTED &&
    millis() - connectionStart < 20000
  ) {
    delay(250);
  }

  wasConnected =
    WiFi.status() == WL_CONNECTED;

  lastReconnect = millis();

  if (wasConnected) {
    Serial.println("Wi-Fi connected");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("Waiting for hotspot");
  }

  server.on("/", HTTP_GET, []() {
    server.sendHeader(
      "Cache-Control",
      "no-store"
    );

    server.send_P(
      200,
      "text/html",
      PAGE
    );
  });

  server.on(
    "/command",
    HTTP_POST,
    handleCommand
  );

  server.on(
    "/status",
    HTTP_GET,
    handleStatus
  );

  server.begin();

  Serial.println("RC Controller ready");
}

// ===== MAIN LOOP =====

void loop() {
  checkTimeouts();

  maintainWiFi();

  server.handleClient();

  checkTimeouts();

  delay(1);
}
