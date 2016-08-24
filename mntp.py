from __future__ import division
import sys
import subprocess
import time
import numpy
from math import sqrt

DEBUG = False
RSSI_THRESHOLD = -75
NOISE_THRESHOLD = -70
SNR_THRESHOLD = 20

expEpoch = 0

def getTS():
    curTime = int(time.time())
    ts = curTime - expEpoch
    return ts

def printVal(label, val, ts = -1):
    if ts == -1:
        ts = getTS()
    print("{0},{1},{2}".format(ts,label,val))

def allowRequest():
    try:
        p = subprocess.Popen(['/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I'], stdout=subprocess.PIPE, stderr=None, shell=True)
        for l in iter(p.stdout.readline,''):
            if "agrCtlRSSI:" in l:
                rssi = int(l.strip().split(": ")[1])
            elif "agrCtlNoise" in l:
                noise = int(l.strip().split(": ")[1])
        if (DEBUG):
            print "rssi ", rssi
            print "noise", noise
            print "snr", rssi-noise

        if rssi > RSSI_THRESHOLD:
            goodRssi = True
        else:
            goodRssi = False

        if noise < NOISE_THRESHOLD:
            goodNoise = True
        else:
            goodNoise = False

        snr = rssi - noise
        if snr < SNR_THRESHOLD:
            goodSnr = False
        else:
            goodSnr = True

        
        if goodRssi and goodNoise and goodSnr:
            allow = True
        else:
            allow = False
        
        printVal("snr", [allow, rssi, noise, snr])

        if (DEBUG):
            print "Allowed ", allow

        return allow
    except:
        return 'NA'

def getOffset(server='0.pool.ntp.org'):
    if (DEBUG): print "In getOffset"
    allow = allowRequest()
    if not allow or allow == 'NA':
        return 'NA'
    
    try:
        p = subprocess.Popen(['sntp', server], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        val, err = p.communicate()
        if (DEBUG):
            print "sntp output ", val
            print "sntp err ", err
        offset = float(val.split(" ")[4])
        return offset * 1000.0   # Return offset in ms
    except:
        return 'NA'

def getAccurateOffset():
    if (DEBUG): print "In getAccurateOffset"

    offsets = []
    for i in range(0,3):
        server = "%d.pool.ntp.org"%(i)
        if (DEBUG):
            print server
        off = 'NA'
        while off == 'NA':
            off = getOffset(server)
            if (DEBUG): print off
            time.sleep(1)
        
        offsets.append(off)
        #time.sleep(5)

    m = numpy.mean(offsets)
    s = numpy.std(offsets)

    selections = []
    group0 = []
    group1 = []
    for off in offsets:
        if off < m-s or off > m+s:
            selections.append(0)
            group0.append(off)
        else:
            selections.append(1)
            group1.append(off)

    if selections.count(1) > selections.count(0):
        finalOffset = min(group1)
    else:
        finalOffset = min(group0)

    if (DEBUG):
        print "All offsets: ", offsets
        print "Selected: ", selections
        print "Final offset: ", finalOffset
    
    return finalOffset

def calculateDrift(offsets, durations):
    totalDuration = sum(durations)
    if (DEBUG):
        print "Offsets : ", offsets
        print "totalDuration : ", totalDuration

    x = range(0,len(offsets))
    pf = numpy.polyfit(x, offsets,1)
    fit = numpy.poly1d(pf)(x)

    if (DEBUG):
        print "Fitted line: ", fit

    drift = (fit[-1] - fit[0]) / totalDuration
    return drift

def correctDrift(drift):
    #print "drift correction: ", drift
    printVal("drift_correction", drift)

def correctClock(offset, offsetTs):
    #print "clock correction: ", offset
    printVal("clock_correction", offset, offsetTs)

def validate(samples, samplesTs, offset, offsetTs):
    allow = True
    if offset == 'NA':
        if (DEBUG): 
            print "Invalid offset"
        return False
    if len(samples) < 10:
        return True

    p = numpy.polyfit(samplesTs, samples, 1)
    yfit = numpy.polyval(p, samplesTs)

    errors = yfit - samples
    sq_errors = [e*e for e in errors]
    meanError = numpy.mean(sq_errors)
    stdError = numpy.std(sq_errors)

    x1 = samplesTs[0]
    y1 = yfit[0]
    x2 = samplesTs[-1]
    y2 = yfit[-1]

    m = (y2-y1)/(x2-x1)
    c = y2 - (m * x2)

    newx = offsetTs
    newy = m * newx + c

    newError = newy - offset
    sq_newError = newError ** 2

    upperThres = meanError + stdError
    lowerThres = meanError - stdError

    if sq_newError < lowerThres or sq_newError > upperThres:
        allow = False
        printVal("validation", [offset, newy, meanError, stdError, allow], offsetTs)

    if(DEBUG):
        print "In Validation"
        print "Ts: {0} Samples: {1}".format(samplesTs, samples)
        print "yfit: {0} Errors: {1} meanError: {2} stdError: {3} newY: {4}".format(yfit, sq_errors, meanError, stdError, newy)
        print "Validation {0}".format([offset, sq_newError, upperThres, lowerThres, allow])
        #if len(samples) > 8:
        #    sys.exit()

    return allow

def runMNTP(warmupCount, warmupWait, regularWait, resetTime):
    inWarmup = True
    localEpoch = 0
    syncEpoch = 0
    samples = []
    durations = []
    samplesTs = []
    driftAvailable = False
    drift = 0

    while True:
        if inWarmup:
            if len(samples) == 0 or syncEpoch >= warmupWait:
                offset = getAccurateOffset()
                offsetTs = getTS()
                if validate(samples, samplesTs, offset, offsetTs):
                    samples.append(offset)
                    samplesTs.append(offsetTs)
                    durations.append(syncEpoch)
                    correctClock(offset, offsetTs)
                    syncEpoch = 0
                    if len(samples) >= warmupCount:
                        inWarmup = False
        else:
            if syncEpoch >= regularWait:
                offset = getOffset()
                if validate(samples, samplesTs, offset, offsetTs):
                    samples.append(offset)
                    samplesTs.append(offsetTs)
                    durations.append(syncEpoch)
                    correctClock(offset, offsetTs)
                    syncEpoch = 0
        
        if not driftAvailable and not inWarmup:
            drift = calculateDrift(samples, durations)
            driftAvailable = True
        elif driftAvailable:
            correctDrift(drift)

        time.sleep(1)
        syncEpoch += 1
        localEpoch += 1

        if (DEBUG):
            print "syncEpoch %d localEpoch %d"%(syncEpoch, localEpoch)

        if localEpoch >= resetTime:
            if (DEBUG): print "Resetting sync cycle"
            inWarmup = True
            localEpoch = 0
            syncEpoch = 0
            samples = []
            durations = []
            samplesTs = []
            driftAvailable = False
            drift = 0

def main():
    global DEBUG
    global expEpoch
    warmupCount = int(sys.argv[1])
    warmupWait = int(sys.argv[2])
    regularWait = int(sys.argv[3])
    resetTime = int(sys.argv[4])
    if len(sys.argv) == 6 and sys.argv[5] == 'debug':
        DEBUG = True

    print "Debug Setting ", DEBUG
    expEpoch = int(time.time())
    runMNTP(warmupCount, warmupWait, regularWait, resetTime)
    #allowRequest()

if __name__ == "__main__":
    main()
