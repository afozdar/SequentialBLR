import mysql.connector
from urllib import urlopen
import json
import numpy as np
import datetime as dt
from algoRunFunctions import movingAverage
from algoRunFunctions import train
from algoRunFunctions import runnable

import matplotlib.pyplot as plt

print "Starting algorithm run..."

with open('config.txt') as f:
    for line in f:
        if line.startswith('HOST'):
            loc = line.find('=')
            hst = line[loc+1:].rstrip()
        elif line.startswith('DATABASE'):
            loc = line.find('=')
            db = line[loc+1:].rstrip()
        elif line.startswith('USER'):
            loc = line.find('=')
            usr = line[loc+1:].rstrip()
        elif line.startswith('PASSWORD'):
            loc = line.find('=')
            pswd = line[loc+1:].rstrip()

config = {
    'user': usr,
    'password': pswd,
    'host': hst,
    'database': db,
    'raise_on_warnings': True
}
cnx = mysql.connector.connect(**config)
cursor = cnx.cursor()
print "Connection made to DB."

with open('/Users/dvorva/Documents/getGraphiteData/sequentialBLR/smartDriver.json') as data_file:
    jsonDataFile = json.load(data_file)
print "Found JSON file."

#Period: length of forecasting window, in hours
#Granularity: time between data, in minutes
matrixLength = int(jsonDataFile["windowSize"])*60/int(jsonDataFile["granularity"])
forecastingInterval = int(jsonDataFile["forecastingInterval"])*60/int(jsonDataFile["granularity"])

inputIDs = jsonDataFile["idSelection"]
inputIDs = inputIDs.split(',')
idArray = []

#Create a list of ID numbers, given input.
#interprets 1-3 to include 1,2,3.
for selection in inputIDs:
    if '-' not in selection:
        idArray.append(int(selection))
    else:
        bounds = selection.split('-')
        for index in range(int(bounds[0]), int(bounds[1])+1):
            idArray.append(index)

#Remove duplicates:
idArray = list(set(idArray))

#Sort the list.
idArray.sort()

#Fill columns with the corresponding column, given IDarray.
#Invariant: the ID in idArray at a given index should correspond
#           to the columnName at the same index in the column list.
startTimeList = []
endTimeList = []
columns = []
lastData = [] #Data point of last valid timestamp - init garbage
lastDataTime = [] #Timestamp of last valid timestamp - init very old [TODO]
for sensorID in idArray:
    columns.append(jsonDataFile["data"][sensorID-1]["columnName"])
    startTimeList.append(jsonDataFile["data"][sensorID-1]["startTime"])
    endTimeList.append(jsonDataFile["data"][sensorID-1]["endTime"])
    lastDataTime.append(dt.datetime.min)
    lastData.append(-1)

#Add total energy consumption column:
columns.append(jsonDataFile["totalConsum"]);
lastData.append(-1)
lastDataTime.append(dt.datetime.min)

#Find latest start time, earliest end time.
startTime = dt.datetime.strptime(max(startTimeList), "%Y-%m-%d %H:%M:%S")
endTime = dt.datetime.strptime(min(endTimeList), "%Y-%m-%d %H:%M:%S")

if(int(jsonDataFile["specifyTime"])):
   startTime = dt.datetime.strptime(jsonDataFile["beginTime"], "%Y-%m-%d %H:%M:%S")
   endTime = dt.datetime.strptime(jsonDataFile["endTime"], "%Y-%m-%d %H:%M:%S")

granularityInSeconds = int(jsonDataFile["granularity"])*60

#X window init.
X =  np.zeros([matrixLength, len(columns)])
Xt =  [None]*matrixLength
y = [None]*matrixLength

print "Beginning analysis."

y_predictions = []
y_target = []
y_time = []
w_opt = []
a_opt = 0
b_opt = 0
rowCount = 1
initTraining = 0


count123 = 1 #for debug
while startTime < endTime:

    if(rowCount % 250 == 0):
        print "trying time: %s " % startTime

    #Build the query:
    isFirst = 1
    qry = "SELECT "
    for column in columns:
        if isFirst == 0:
            qry += ", "
        else:
            isFirst = 0
        qry = qry + column

    qry = qry + " FROM SMART WHERE dataTime BETWEEN %s AND %s"

    #Execute the query:
    cursor.execute(qry , (startTime, startTime + dt.timedelta(0,granularityInSeconds)))

    #Get the average in the queried window: (should probably switch this to be done by qry)
    colSum = np.zeros(len(columns))
    colCount = np.zeros(len(columns))
    for row in cursor:
        i = 0
        for columnData in row:
            if columnData is not None:
                colSum[i] += columnData
                colCount[i] += 1
            i += 1

    #Update X,Xt,y
    Xt[(rowCount-1) % matrixLength] = startTime
    for i in range(0, len(columns)):
        #We have new valid data! Also update lastData
        if colSum[i] > 0:
            if "motion" in columns[i]:
                X[(rowCount-1) % matrixLength][i] = colSum[i]
                lastData[i] = colSum[i]
            else:
                X[(rowCount-1) % matrixLength][i] = colSum[i] / colCount[i]
                lastData[i] = colSum[i] / colCount[i]

            lastDataTime[i] = startTime
        #No new data.
        else:
            X[(rowCount-1) % matrixLength][i] = lastData[i]

    # Time to train:
    if(rowCount % forecastingInterval == 0 and rowCount >= matrixLength):
        data = X[(rowCount % matrixLength):,0:len(columns)-1]
        data = np.concatenate((data, X[0:(rowCount % matrixLength), 0:len(columns)-1]), axis=0)
        y = X[(rowCount % matrixLength):, len(columns)-1]
        y = np.concatenate((y, X[:(rowCount % matrixLength), len(columns)-1]), axis=0)
        if(initTraining or runnable(data) > 0.5):
            #'Unwrap' the data matrices
            #time = Xt[(rowCount % matrixLength):]
            #time += Xt[:(rowCount % matrixLength)]
            w_opt, a_opt, b_opt, S_N = train(data, y)
            initTraining = 1
#            if startTime > dt.datetime.strptime("2012-05-07 10:00:03", "%Y-%m-%d %H:%M:%S") and startTime < dt.datetime.strptime("2012-05-07 10:30:03", "%Y-%m-%d %H:%M:%S"):
#                text = "test" + str(count123) + ".txt"
#                np.savetxt(text, data, fmt='%10.5f', delimiter=',')   # X is an array
#                print startTime
#                print "W_OPT %s " % w_opt
#                print "ALPHA %s " % a_opt
#                print "BETA %s " % b_opt
#                print count123
#                count123 = count123 + 1
#                if b_opt > 1:
#                    print data

#            if startTime > dt.datetime.strptime("2012-05-22 23:00:03", "%Y-%m-%d %H:%M:%S") and startTime < dt.datetime.strptime("2012-05-23 21:30:03", "%Y-%m-%d %H:%M:%S"):
#                print startTime
#                print "W_OPT %s " % w_opt
#                print "ALPHA %s " % a_opt
#                print "BETA %s " % b_opt


    #make prediction:
    if(initTraining):
        x_n = X[(rowCount-1) % matrixLength][:len(columns)-1]
        #y_predictions[n] = max(0, np.inner(w_opt,x_n))
        #error = (y_predictions[n]-y_target[n])
        #sigma = np.sqrt(1/b_opt + np.dot(np.transpose(x_n),np.dot(S_N, x_n)))

        y_time.append(Xt[(rowCount-1) % matrixLength])
        y_predictions.append(max(0, np.inner(w_opt,x_n)))
        y_target.append(X[(rowCount-1) % matrixLength][len(columns)-1])


#        if startTime > dt.datetime.strptime("2012-05-07 10:00:03", "%Y-%m-%d %H:%M:%S") and startTime < dt.datetime.strptime("2012-05-07 10:30:03", "%Y-%m-%d %H:%M:%S"):
#            print startTime
#            print x_n

    #Increment and loop
    startTime += dt.timedelta(0,granularityInSeconds)
    rowCount += 1
                              

print "Analysis complete."
print "Graphing and statistics..."

# Hereafter is just result reporting and graphing
# Prediction accuracy
n_samples = rowCount-1
training = int(jsonDataFile["windowSize"])*(60 / int(jsonDataFile["granularity"])) #init prediction period.
T = n_samples-training #prediction length
smoothing_win = 120
y_target = np.asarray(y_target)
y_predictions = np.asarray(y_predictions)
y_target_smoothed = movingAverage(y_target, smoothing_win)
y_predictions_smoothed = movingAverage(y_predictions, smoothing_win)
rmse_smoothed = []
rmse = []
Re_mse = []
smse = []
co95 = []

# Prediction Mean Squared Error (smooth values)

PMSE_score_smoothed = np.linalg.norm(y_target_smoothed-y_predictions_smoothed)**2 / T
# Prediction Mean Squared Error (raw values)
PMSE_score = np.linalg.norm(y_target - y_predictions)**2 / T

confidence = 1.96 / np.sqrt(T) *  np.std(np.abs(y_target-y_predictions))
# Relative Squared Error
Re_MSE = np.linalg.norm(y_target-y_predictions)**2 / np.linalg.norm(y_target)**2
# Standardise Mean Squared Error
SMSE =  np.linalg.norm(y_target-y_predictions)**2 / T / np.var(y_target)
    
rmse_smoothed.append(np.sqrt(PMSE_score_smoothed))
rmse.append(np.sqrt(PMSE_score))
co95.append(confidence)
Re_mse.append(Re_MSE)
smse.append(SMSE)


print "PMSE for smoothed: %d" % (PMSE_score_smoothed)
print "PMSE for nonsmoothed: %d" % (PMSE_score)
print "------------------------------------------------------------------------------------------------------"
print "%20s |%20s |%25s |%20s" % ("RMSE-score (smoothed)", "RMSE-score (raw)", "Relative MSE", "SMSE")
print "%20.2f  |%20.2f |%25.2f |%20.2f " % (np.mean(np.asarray(rmse_smoothed)), np.mean(np.asarray(rmse)), np.mean(np.asarray(Re_mse)), np.mean(np.asarray(smse)))

print "------------------------------------------------------------------------------------------------------"

# red dashes, blue squares and green triangles
#plt.plot(y_time, y_target, 'r--', y_time, y_predictions, 'b--')
plt.plot(y_time, y_target_smoothed, 'r--', y_time, y_predictions_smoothed, 'b--')
#plt.ylim([0,15000])
plt.show()

cursor.close()
cnx.close()



