#include <USB_STREAM.h>

// ESP32-S3 + USB UVC webcam (Arducam) -> MJPEG stream over local network
//
//   http://<esp-ip>/          simple viewer page
//   http://<esp-ip>/stream    MJPEG stream (works in browser, VLC, OBS, Home Assistant...)
//   http://<esp-ip>/snapshot  single JPEG
//
// Camera requirements: UVC, MJPEG output, works at USB full-speed (12 Mbps).

#include <Arduino.h>
#include <WiFi.h>


// ---------- CONFIG ----------
static const char *WIFI_SSID = "realme GT 6 9901";
static const char *WIFI_PASS = "hola:)1234";

#define FRAME_W        FRAME_RESOLUTION_ANY   // let the library pick what the camera offers
#define FRAME_H        FRAME_RESOLUTION_ANY
#define FRAME_INTERVAL FRAME_INTERVAL_FPS_15
#define BUF_SIZE       (100 * 1024)        // must be >= largest MJPEG frame (PSRAM makes this cheap)
// ----------------------------

static USB_STREAM *usb = nullptr;
static WiFiServer server(80);

static uint8_t *xferBufA, *xferBufB, *frameBuf;   // used by the USB library
static uint8_t *latestBuf, *sendBuf;              // latest frame + copy being sent
static size_t latestLen = 0;
static volatile uint32_t frameSeq = 0;
static SemaphoreHandle_t mtx;

static uint8_t *allocBuf(size_t n) {
  uint8_t *p = nullptr;
  if (psramFound()) p = (uint8_t *)ps_malloc(n);
  if (!p) p = (uint8_t *)malloc(n);
  if (!p) { Serial.println("Out of memory - lower resolution / buffer size"); while (true) delay(1000); }
  return p;
}

// Called by the USB task every time a full MJPEG frame arrives
static void onFrame(uvc_frame_t *frame, void *user) {
  if (!frame || frame->data_bytes == 0 || frame->data_bytes > BUF_SIZE) return;
  if (xSemaphoreTake(mtx, pdMS_TO_TICKS(10)) == pdTRUE) {
    memcpy(latestBuf, frame->data, frame->data_bytes);
    latestLen = frame->data_bytes;
    frameSeq++;
    xSemaphoreGive(mtx);
  }
}

// Copy newest frame (if newer than lastSeq) into sendBuf. Returns length or 0.
static size_t grabFrame(uint32_t &lastSeq, bool any = false) {
  size_t len = 0;
  if (xSemaphoreTake(mtx, pdMS_TO_TICKS(100)) == pdTRUE) {
    if (latestLen && (any || frameSeq != lastSeq)) {
      memcpy(sendBuf, latestBuf, latestLen);
      len = latestLen;
      lastSeq = frameSeq;
    }
    xSemaphoreGive(mtx);
  }
  return len;
}

static bool writeAll(WiFiClient &c, const uint8_t *d, size_t n) {
  while (n && c.connected()) {
    size_t w = c.write(d, n);
    if (w == 0) return false;
    d += w; n -= w;
  }
  return n == 0;
}

static void handleClient(WiFiClient c) {
  c.setTimeout(2000);
  String reqLine = c.readStringUntil('\n');
  while (c.connected()) {                       // drain headers
    String l = c.readStringUntil('\n');
    if (l.length() <= 1) break;
  }

  if (reqLine.startsWith("GET /stream")) {
    c.print("HTTP/1.1 200 OK\r\n"
            "Content-Type: multipart/x-mixed-replace; boundary=frame\r\n"
            "Cache-Control: no-cache\r\nConnection: close\r\n\r\n");
    uint32_t seq = 0;
    while (c.connected()) {
      size_t len = grabFrame(seq);
      if (!len) { delay(5); continue; }
      c.printf("--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n", (unsigned)len);
      if (!writeAll(c, sendBuf, len)) break;
      c.print("\r\n");
    }
  } else if (reqLine.startsWith("GET /snapshot")) {
    uint32_t seq = 0;
    size_t len = grabFrame(seq, true);
    if (!len) {
      c.print("HTTP/1.1 503 Service Unavailable\r\nConnection: close\r\n\r\nNo frame yet");
    } else {
      c.printf("HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\nConnection: close\r\n\r\n", (unsigned)len);
      writeAll(c, sendBuf, len);
    }
  } else {
    c.print("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
            "<!doctype html><title>ESP32-S3 cam</title>"
            "<body style='margin:0;background:#111'><img src='/stream' style='width:100%;max-width:960px;display:block;margin:auto'></body>");
  }
  c.stop();
}

void setup() {
  Serial.begin(115200);
  delay(500);

  mtx = xSemaphoreCreateMutex();
  xferBufA  = allocBuf(BUF_SIZE);
  xferBufB  = allocBuf(BUF_SIZE);
  frameBuf  = allocBuf(BUF_SIZE);
  latestBuf = allocBuf(BUF_SIZE);
  sendBuf   = allocBuf(BUF_SIZE);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true);
  delay(200);

  int n = WiFi.scanNetworks();
  Serial.printf("Found %d networks:\n", n);
  for (int i = 0; i < n; i++)
    Serial.printf("  %s  (ch %d, %d dBm)\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i));

  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Connecting to Wi-Fi");
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.printf(" [%d]", WiFi.status());
    if (millis() - t0 > 20000) {
      Serial.println("\nRetrying...");
      WiFi.disconnect(true);
      delay(200);
      WiFi.begin(WIFI_SSID, WIFI_PASS);
      t0 = millis();
    }
  }
  Serial.printf("\nConnected. Open http://%s/\n", WiFi.localIP().toString().c_str());

  usb = new USB_STREAM();
  usb->uvcConfiguration(FRAME_W, FRAME_H, FRAME_INTERVAL,
                        BUF_SIZE, xferBufA, xferBufB,
                        BUF_SIZE, frameBuf);
  usb->uvcCamRegisterCb(&onFrame, nullptr);
  usb->start();
  Serial.println("Waiting for USB camera...");
  usb->connectWait(10000);
  Serial.println("USB camera step done (check log above if no frames arrive)");

  server.begin();
}

void loop() {
  WiFiClient c = server.accept();
  if (c) handleClient(c);                       // one client at a time
  delay(2);
}
