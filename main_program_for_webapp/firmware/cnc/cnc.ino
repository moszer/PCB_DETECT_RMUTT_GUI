/* Nano / 28BYJ-48 / ULN2003. X: D4..7, Y: D8..11; NO limits: D2,D3.
 * Protocol v2: @id MOVE absoluteX absoluteY speed -> ACK, POS, DONE/ERR.
 * One active operation. The host owns the bounded queue. STOP/OFF preempt it.
 * Idle coils are switched off IDLE_RELEASE_MS after each command finishes (the 28BYJ-48 runs
 * hot when held); position and HOME are kept: the 1:64 gearbox holds the axis, and the next
 * MOVE re-energizes the same coil phase. OFF still clears HOME; RELEASE switches off now.
 * HOME touches each switch several times: fast seek, then FINE_TOUCHES slow approaches from
 * FINE_BACKOFF away; zero is the mean trigger point (+BACKOFF), and "[HOMEINFO] axis spread
 * touches" reports how far apart the touches were (steps), i.e. the switch repeatability.
 * TONE f ms [mask] [swing]: buzz the motors at f Hz (50-4000) for ms (5-5000) by flipping the
 * coils between two steps around the current one, `swing` half-steps apart (1 = current/next,
 * 2 = -1/+1, 4 = -2/+2: wider is louder); they end on the current step, so position and HOME
 * stay. mask: 1 = X, 2 = Y, 3 = both (default). ACK, then DONE when it ends.
 */
#include <AccelStepper.h>
#include <EEPROM.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

class AxisStepper : public AccelStepper {
public:
  AxisStepper(uint8_t a, uint8_t b, uint8_t c, uint8_t d)
    : AccelStepper(8, a, b, c, d) {}
  void hold() { enableOutputs(); step(currentPosition()); }
  // Coils of a step `offset` half-steps from the current one, without moving the counter.
  void buzz(int offset) { step(currentPosition() + offset); }
  void advance(int direction) {
    setCurrentPosition(currentPosition()+direction);
    step(currentPosition());
  }
};
AxisStepper stepperX(4,6,5,7), stepperY(8,10,9,11);
long pathDx=0, pathDy=0, pathSpan=0, errorX=0, errorY=0;
int directionX=1, directionY=1;
void pathStep() {
  errorX+=pathDx; errorY+=pathDy;
  if (errorX>=pathSpan) { errorX-=pathSpan; stepperX.advance(directionX); }
  if (errorY>=pathSpan) { errorY-=pathSpan; stepperY.advance(directionY); }
}
void unusedReverseStep() {}
// A virtual accelerated axis clocks a Bresenham line on the two physical axes.
AccelStepper pathStepper(pathStep,unusedReverseStep);
const uint8_t PIN_LIMIT_X=2, PIN_LIMIT_Y=3;
const long STEPS_PER_REV=4096, BACKOFF=1024;
const float STEPS_PER_MM=512.0, ACCEL=600.0;
long maxX=19456, maxY=19456; // 38.00 mm @ 512 steps/mm
float currentSpeed=1000;
bool homed=false, coilsOff=true;
enum Phase { IDLE, MOVING, RELEASE, SEEK, BACKING, TONE, FINE_BACK, FINE_SEEK };
Phase phase=IDLE;
bool calibrating=false, bothAxes=true;
uint8_t homeAxis=0;
long phaseStart=0, measuredX=0, measuredY=0;
unsigned long activeId=0, phaseTime=0, lastTelemetry=0;
unsigned long lastHostMessage=0;
const unsigned long IDLE_RELEASE_MS=3000; // longer than a scan point's capture, so a scan keeps them on
unsigned long idleSince=0;
// Fine homing: slow, repeated touches of the switch from the same side.
const uint8_t FINE_TOUCHES=3;
const long FINE_BACKOFF=200;   // ~0.4 mm off the switch before each slow touch
const float FINE_SPEED=150;    // steps/s for the touches (fast seek is 600)
long fineHits[FINE_TOUCHES];
uint8_t fineCount=0, limitStreak=0;
unsigned long toneHalfUs=0, toneLast=0, toneEnd=0;
uint8_t toneMask=0;
bool toneNext=false;
int toneLow=0, toneHigh=1;
char inputLine[96];
uint8_t inputLength=0;
bool inputOverflow=false;

struct CalibrationRecord { uint32_t magic; int32_t x; int32_t y; uint32_t checksum; };
void saveCalibration() {
  CalibrationRecord record={0x434e4332UL,(int32_t)maxX,(int32_t)maxY,0};
  record.checksum=record.magic ^ (uint32_t)record.x ^ (uint32_t)record.y;
  EEPROM.put(0,record);
}
void loadCalibration() {
  CalibrationRecord record;
  EEPROM.get(0,record);
  if (record.magic==0x434e4332UL && record.x>0 && record.x<=100000 && record.y>0 && record.y<=100000 &&
      record.checksum==(record.magic ^ (uint32_t)record.x ^ (uint32_t)record.y)) {
    maxX=record.x; maxY=record.y;
  }
}

bool limitX() { return digitalRead(PIN_LIMIT_X)==LOW; }
bool limitY() { return digitalRead(PIN_LIMIT_Y)==LOW; }
AccelStepper &axis() { return homeAxis==0 ? (AccelStepper&)stepperX : (AccelStepper&)stepperY; }
bool axisLimit() { return homeAxis==0 ? limitX() : limitY(); }
// The switch counts as pressed after 3 reads in a row (a bounce or a noise spike does not).
bool axisLimitSteady() { limitStreak = axisLimit() ? (uint8_t)min(limitStreak + 1, 10) : 0; return limitStreak >= 3; }

void positionFields() {
  Serial.print(stepperX.currentPosition()); Serial.print(' ');
  Serial.print(stepperY.currentPosition()); Serial.print(' ');
  Serial.println(homed ? 1 : 0);
}
void reportPosition() { Serial.print(F("[POS] ")); Serial.print(activeId); Serial.print(' '); positionFields(); }
void reportLimits() {
  Serial.print(F("[LIMITS] ")); Serial.print(limitX()?1:0); Serial.print(' '); Serial.println(limitY()?1:0);
}
void reportReady() {
  Serial.print(F("[READY] 2 "));
  Serial.print(stepperX.currentPosition()); Serial.print(' ');
  Serial.print(stepperY.currentPosition()); Serial.print(' ');
  Serial.print(maxX); Serial.print(' '); Serial.print(maxY); Serial.print(' ');
  Serial.println(homed?1:0);
}
void reject(unsigned long id, const __FlashStringHelper *reason) {
  Serial.print(F("[ERR] ")); Serial.print(id); Serial.print(' '); Serial.print(reason); Serial.print(' '); positionFields();
}
void endTone() {
  if (toneMask & 1) stepperX.buzz(0);
  if (toneMask & 2) stepperY.buzz(0);
  toneMask=0;
}
void haltMotion() {
  if (phase==TONE) endTone();
  pathStepper.setCurrentPosition(0);
  stepperX.setCurrentPosition(stepperX.currentPosition());
  stepperY.setCurrentPosition(stepperY.currentPosition());
  phase=IDLE;
}
void powerOff() {
  stepperX.disableOutputs(); stepperY.disableOutputs(); coilsOff=true;
}
void powerOn() { stepperX.hold(); stepperY.hold(); coilsOff=false; }
void acknowledge(unsigned long id) { Serial.print(F("[ACK] ")); Serial.println(id); }
void complete() {
  phase=IDLE; idleSince=millis();
  Serial.print(F("[DONE] ")); Serial.print(activeId); Serial.print(' '); positionFields();
  activeId=0;
}
void fail(const __FlashStringHelper *reason) {
  haltMotion(); homed=false; powerOff(); reject(activeId,reason); activeId=0;
}

void startHomeAxis() {
  AccelStepper &s=axis();
  s.setCurrentPosition(s.currentPosition()); s.setMaxSpeed(800); s.setAcceleration(ACCEL);
  phaseStart=s.currentPosition(); phaseTime=millis(); limitStreak=0;
  if (axisLimit()) { phase=RELEASE; s.setSpeed(400); }
  else { phase=SEEK; s.setCurrentPosition(0); s.setSpeed(-600); }
}
void startHoming(unsigned long id, bool cal, uint8_t first, bool both) {
  activeId=id; calibrating=cal; homeAxis=first; bothAxes=both; homed=false;
  measuredX=maxX; measuredY=maxY;
  powerOn(); acknowledge(id); startHomeAxis();
}
void runHoming() {
  AccelStepper &s=axis();
  if (phase==RELEASE) {
    if (!axisLimit()) { s.setCurrentPosition(0); s.setSpeed(-600); phase=SEEK; phaseTime=millis(); }
    else if (labs(s.currentPosition()-phaseStart)>=4096 || millis()-phaseTime>15000UL) { fail(F("SWITCH_STUCK")); }
    else s.runSpeed();
  } else if (phase==SEEK) {
    if (axisLimitSteady()) {
      long length=labs(s.currentPosition())-BACKOFF;
      if (calibrating && length<=0) { fail(F("CAL_TOO_SHORT")); return; }
      if (homeAxis==0) measuredX=length; else measuredY=length;
      // Found fast; now touch it slowly several times from just off the switch.
      s.setCurrentPosition(0); s.setMaxSpeed(600); s.setAcceleration(ACCEL); s.moveTo(FINE_BACKOFF);
      fineCount=0; limitStreak=0; phase=FINE_BACK; phaseTime=millis();
    } else if (labs(s.currentPosition()) >= (calibrating?100000L:50000L) || millis()-phaseTime>240000UL) {
      fail(F("HOME_TIMEOUT"));
    } else s.runSpeed();
  } else if (phase==FINE_BACK) {
    s.run();
    if (millis()-phaseTime>15000UL) { fail(F("BACKOFF_TIMEOUT")); return; }
    if (s.distanceToGo()==0 && s.speed()==0) {
      if (axisLimit()) { fail(F("SWITCH_STUCK")); return; }
      phaseStart=s.currentPosition(); limitStreak=0;
      s.setSpeed(-FINE_SPEED); phase=FINE_SEEK; phaseTime=millis();
    }
  } else if (phase==FINE_SEEK) {
    if (axisLimitSteady()) {
      long hit=s.currentPosition();
      fineHits[fineCount++]=hit;
      if (fineCount<FINE_TOUCHES) {
        s.setMaxSpeed(600); s.setAcceleration(ACCEL); s.moveTo(hit+FINE_BACKOFF);
        limitStreak=0; phase=FINE_BACK; phaseTime=millis();
        return;
      }
      long lo=fineHits[0], hi=fineHits[0], sum=0;
      for (uint8_t i=0; i<FINE_TOUCHES; i++) { lo=min(lo,fineHits[i]); hi=max(hi,fineHits[i]); sum+=fineHits[i]; }
      long mean=(sum + (sum>=0 ? FINE_TOUCHES/2 : -(long)(FINE_TOUCHES/2))) / FINE_TOUCHES;
      s.setCurrentPosition(hit-mean);  // zero = mean trigger point
      Serial.print(F("[HOMEINFO] ")); Serial.print(homeAxis==0?'X':'Y'); Serial.print(' ');
      Serial.print(hi-lo); Serial.print(' '); Serial.println(FINE_TOUCHES);
      s.setMaxSpeed(600); s.setAcceleration(ACCEL); s.moveTo(BACKOFF);
      phase=BACKING; phaseTime=millis();
    } else if (labs(s.currentPosition()-phaseStart) > 2*FINE_BACKOFF+200 || millis()-phaseTime>15000UL) {
      fail(F("FINE_HOME_FAIL"));  // switch not found again where it was: loose switch or slipping
    } else s.runSpeed();
  } else if (phase==BACKING) {
    s.run();
    if (millis()-phaseTime>15000UL) { fail(F("BACKOFF_TIMEOUT")); return; }
    if (s.distanceToGo()==0 && s.speed()==0) {
      if (axisLimit()) { fail(F("SWITCH_STUCK")); return; }
      s.setCurrentPosition(0);
      if (bothAxes && homeAxis==0) { homeAxis=1; startHomeAxis(); }
      else {
        homed=bothAxes;
        if (calibrating) {
          maxX=measuredX; maxY=measuredY;
          saveCalibration();
          Serial.print(F("[CONFIG] ")); Serial.print(maxX); Serial.print(' '); Serial.println(maxY);
        }
        complete(); reportLimits();
      }
    }
  }
}

void startTone(unsigned long id, long freq, long ms, long mask, long swing) {
  if (freq<50 || freq>4000 || ms<5 || ms>5000 || mask<1 || mask>3 || swing<1 || swing>4) { reject(id,F("BAD_TONE")); return; }
  toneLow=-(int)(swing/2); toneHigh=(int)swing+toneLow;
  activeId=id; acknowledge(id); powerOn();
  toneHalfUs=500000UL/(unsigned long)freq; toneEnd=millis()+(unsigned long)ms;
  toneLast=micros(); toneNext=false; toneMask=(uint8_t)mask; phase=TONE;
}
void runTone() {
  if ((long)(millis()-toneEnd)>=0) { endTone(); complete(); return; }
  unsigned long now=micros();
  if (now-toneLast>=toneHalfUs) {
    toneLast+=toneHalfUs; toneNext=!toneNext;
    if (toneMask & 1) stepperX.buzz(toneNext ? toneHigh : toneLow);
    if (toneMask & 2) stepperY.buzz(toneNext ? toneHigh : toneLow);
  }
}

void startMove(unsigned long id, long x, long y, long speed) {
  if (!homed) { reject(id,F("HOME_REQUIRED")); return; }
  if (x<0 || x>maxX || y<0 || y>maxY) { reject(id,F("OUT_OF_BOUNDS")); return; }
  if (speed<20 || speed>1500) { reject(id,F("BAD_SPEED")); return; }
  long dx=labs(x-stepperX.currentPosition()), dy=labs(y-stepperY.currentPosition());
  long span=max(dx,dy);
  activeId=id; acknowledge(id);
  if (span==0) { complete(); return; }
  powerOn(); currentSpeed=speed;
  pathDx=dx; pathDy=dy; pathSpan=span;
  directionX=x>=stepperX.currentPosition()?1:-1;
  directionY=y>=stepperY.currentPosition()?1:-1;
  errorX=errorY=span/2;
  pathStepper.setCurrentPosition(0);
  pathStepper.setMaxSpeed(speed); pathStepper.setAcceleration(ACCEL);
  pathStepper.moveTo(span); phase=MOVING;
}

bool parseLong(const char *s, long &value) {
  if (!s || !*s) return false;
  char *end; double n=strtod(s,&end);
  if (*end || !isfinite(n) || n < -1000000000.0 || n > 1000000000.0 || floor(n)!=n) return false;
  value=(long)n; return true;
}
bool parseFloat(const char *s, double &value) {
  if (!s || !*s) return false;
  char *end; value=strtod(s,&end);
  return !*end && isfinite(value) && fabs(value)<=100000;
}
void processLine(char *line) {
  char *tokens[7]; uint8_t count=0;
  char *t=strtok(line," \t\r");
  while (t && count<7) { tokens[count++]=t; t=strtok(NULL," \t\r"); }
  if (!count) return;
  unsigned long id=0; uint8_t p=0;
  if (tokens[0][0]=='@') {
    long value;
    if (!parseLong(tokens[0]+1,value) || value<=0) { reject(0,F("BAD_ID")); return; }
    id=value; p=1;
  }
  if (p>=count) { reject(id,F("BAD_COMMAND")); return; }
  char *cmd=tokens[p++];
  for (char *c=cmd; *c; ++c) *c=toupper(*c);
  uint8_t args=count-p;
  lastHostMessage=millis();
  if (!strcmp(cmd,"PING") && !args) return;
  if ((!strcmp(cmd,"STOP") || !strcmp(cmd,"OFF")) && !args) {
    bool interruptedHome=phase==RELEASE || phase==SEEK || phase==BACKING || phase==FINE_BACK || phase==FINE_SEEK;
    haltMotion(); if (interruptedHome) homed=false;
    if (!strcmp(cmd,"OFF")) { powerOff(); homed=false; }
    activeId=id; acknowledge(id); complete(); return;
  }
  if (!strcmp(cmd,"HELLO") && !args) { reportReady(); reportLimits(); return; }
  if ((!strcmp(cmd,"QUERY") || !strcmp(cmd,"POS") || !strcmp(cmd,"CAL") || !strcmp(cmd,"STATUS") || !strcmp(cmd,"LIMITS")) && !args) {
    reportPosition(); reportLimits(); return;
  }
  if ((!strcmp(cmd,"?") || !strcmp(cmd,"HELP")) && !args) {
    Serial.println(F("CNC v2: HOME AUTOCAL MOVE x y speed X/Y/XY/XD/YD/XR/YR S STOP OFF ON RELEASE TONE POS")); return;
  }
  if (phase!=IDLE) { reject(id,F("BUSY")); return; }
  if ((!strcmp(cmd,"HOME") || !strcmp(cmd,"G28")) && !args) { startHoming(id,false,0,true); return; }
  if ((!strcmp(cmd,"AUTOCAL") || !strcmp(cmd,"CALIBRATE") || !strcmp(cmd,"CAL_RAIL") || !strcmp(cmd,"CALIBRATE_RAIL")) && !args) { startHoming(id,true,0,true); return; }
  if ((!strcmp(cmd,"CAL_X") || !strcmp(cmd,"AUTOCAL_X")) && !args) { startHoming(id,true,0,false); return; }
  if ((!strcmp(cmd,"CAL_Y") || !strcmp(cmd,"AUTOCAL_Y")) && !args) { startHoming(id,true,1,false); return; }
  if ((!strcmp(cmd,"SETHOME") || !strcmp(cmd,"SETZERO")) && !args) { reject(id,F("USE_HOME")); return; }
  if (!strcmp(cmd,"ON") && !args) { powerOn(); activeId=id; acknowledge(id); complete(); return; }
  if (!strcmp(cmd,"RELEASE") && !args) { powerOff(); activeId=id; acknowledge(id); complete(); return; }
  if (!strcmp(cmd,"TONE") && args>=2 && args<=4) {
    long f, ms, mask=3, swing=1;
    if (parseLong(tokens[p],f) && parseLong(tokens[p+1],ms) && (args<3 || parseLong(tokens[p+2],mask)) &&
        (args<4 || parseLong(tokens[p+3],swing))) { startTone(id,f,ms,mask,swing); return; }
  }
  long x,y,speed;
  if (!strcmp(cmd,"S") && args==1 && parseLong(tokens[p],speed) && speed>=20 && speed<=1500) {
    currentSpeed=speed; activeId=id; acknowledge(id); complete(); return;
  }
  if (!strcmp(cmd,"MOVE") && args==3 && parseLong(tokens[p],x) && parseLong(tokens[p+1],y) && parseLong(tokens[p+2],speed)) { startMove(id,x,y,speed); return; }
  long dx=0,dy=0;
  bool valid=false;
  if (!strcmp(cmd,"XY") && args==2) valid=parseLong(tokens[p],dx) && parseLong(tokens[p+1],dy);
  else if ((!strcmp(cmd,"X") || !strcmp(cmd,"Y")) && args==1) {
    long amount; valid=parseLong(tokens[p],amount); if (valid) { if (cmd[0]=='X') dx=amount; else dy=amount; }
  } else if ((!strcmp(cmd,"XD") || !strcmp(cmd,"YD") || !strcmp(cmd,"XR") || !strcmp(cmd,"YR")) && args==1) {
    double value; valid=parseFloat(tokens[p],value);
    if (valid) { long steps=(long)(value*STEPS_PER_REV/(cmd[1]=='D'?360.0:1.0)); if (cmd[0]=='X') dx=steps; else dy=steps; }
  }
  if (valid) { startMove(id,stepperX.currentPosition()+dx,stepperY.currentPosition()+dy,(long)currentSpeed); return; }
  reject(id,F("BAD_COMMAND"));
}

void checkSerial() {
  // Bounded work per tick lets stepping and safety run even under serial spam.
  uint8_t budget=32;
  while (budget-- && Serial.available()>0) {
    char c=(char)Serial.read();
    if (c=='\n' || c=='\r') {
      if (inputOverflow) reject(0,F("LINE_TOO_LONG"));
      else if (inputLength) { inputLine[inputLength]='\0'; processLine(inputLine); }
      inputLength=0; inputOverflow=false;
    } else if (!inputOverflow) {
      if (inputLength<sizeof(inputLine)-1) inputLine[inputLength++]=c;
      else inputOverflow=true;
    }
  }
}
void setup() {
  loadCalibration();
  Serial.begin(9600); pinMode(PIN_LIMIT_X,INPUT_PULLUP); pinMode(PIN_LIMIT_Y,INPUT_PULLUP);
  stepperX.setMaxSpeed(currentSpeed); stepperY.setMaxSpeed(currentSpeed);
  stepperX.setAcceleration(ACCEL); stepperY.setAcceleration(ACCEL);
  powerOff(); reportReady(); reportLimits();
}
void loop() {
  checkSerial();
  if (phase!=IDLE && activeId>0 && millis()-lastHostMessage>3000UL) fail(F("LINK_TIMEOUT"));
  if (phase==MOVING) {
    if ((limitX() && pathDx>0 && directionX<0) || (limitY() && pathDy>0 && directionY<0)) { fail(F("LIMIT_HIT")); reportLimits(); }
    else {
      pathStepper.run();
      if (!pathStepper.isRunning()) complete();
    }
  } else if (phase==TONE) runTone();
  else if (phase!=IDLE) runHoming();
  // Keep idle motors cool; homed and the step counters are untouched.
  if (phase==IDLE && !coilsOff && millis()-idleSince>=IDLE_RELEASE_MS) powerOff();
  // No telemetry while buzzing: serial writes would put a stutter into the tone.
  if (phase!=IDLE && phase!=TONE && millis()-lastTelemetry>=250) { lastTelemetry=millis(); reportPosition(); }
}
