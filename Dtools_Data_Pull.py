"""
File: Dtools_Data_Pull.py
Associated Files: AUTHENTICATION, LICENSE
Required Packages: requests 
License: Apache-2.0
Date Created: 18Feb2025
Last Modified: 27Mar2025 by John Lukowski

Purpose: Using a gui to select API data fields, perform API calls to
the Dtools cloud and export the results in a structured csv file.
Has the ability to pull data locally based on previous API calls to
lessen number of calls if accuracy is not 100% needed
AUTHENTICATION file (not included) is a string file containing a base64
encoded JSON in the format:
{
    'username':'xxxxx',
    'password':'xxxxx',
    'key':'xxxxx'
}
where these are the username/password and api key for dtools cloud
"""

### Authorship Information
__version__ = '1.0'
__author__ = 'John Lukowski, Excel Communications Worldwide'
__email__ = 'jlukowski@excelcom.net'
__copyright__ = 'Copyright 2025 John Lukowski'
__license__ = """
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
__all__ = ['DtoolsAPI']

### Standard Imports
import functools
import json
import sys
import time
import csv
import os
import logging
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from base64 import b64encode, b64decode
from os import makedirs
from threading import Thread
from datetime import datetime

### 3rd Party Imports
import requests # pip install requests

### Static Variables
ERR_LOG_FILE = 'Dtools.log'
CSV_FILE_BASE = 'Dtools_Opportunity_Hours'
HOURS_FILE = 'Dtools_All_Hours'
OPP_FILE = 'Dtools_Opps_List'
DETAILS_PATH = 'OpportunityDetails'
QUOTES_PATH = 'QuoteDetails'
CHANGE_PATH = 'ChangeDetails'
CSV_OPTIONS = {
    'Job ID':'id',
    'Client Name':'clientName',
    'Job Name':'name',
    'Job Stage':'stage',
    'Job Priority':'priority',
    'Job Price':'price',
    'Labor Type':'laborType',
    'Quoted Minutes':'quoteMinutes',
    'Worked Minutes':'jobMinutes'
}
API_LOG_FILE = 'Dtools_API_Calls.txt'
API_URL_BASE = 'https://dtcloudapi.d-tools.cloud/api/v1'
API_PATH_TIME = '/TimeEntries/GetTimeEntries?page=1&pageSize=6000'
API_PATH_OPP = '/Opportunities/GetOpportunities' +\
    '?stages=New%20Sales%20Opportunity' +\
    '&stages=Opportunity%20Won' +\
    '&stages=Qualifying%20%26%20Consulting' +\
    '&stages=Quote%20Development%20%28See%20Quote%20States%29' +\
    '&stages=Negotiating%2C%20Reviews' +\
    '&stages=On%20Hold&sort=Price%20DESC' +\
    '&page=1' +\
    '&pageSize=3000'

# Start an error logger for important steps and errors
ERR_LOG = logging.getLogger(__name__)

def writeFile(fileName, data):
    """
    writeFile is a function meant write given data
    to a given file

    :param fileName: string path/name of the file
    :param data: string data to write to file
    :return: None
    """
    with open(fileName, 'w') as file:
        json.dump(data, file)

def readFile(fileName):
    """
    readFile is a function meant to read in data
    from a given file, return None if doesnt exist

    :param fileName: string path/name of the file
    :return: file contents string or None
    """
    try:
        with open(fileName, 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        ERR_LOG.warning(f'File not found: {fileName}')
        return None
    except Exception as e:
        ERR_LOG.warning(f'File error: {fileName}: {str(e)}')
        return None

def safeExit(errCode, *args, **kwargs):
    if 'api' in kwargs:
        kwargs['api'].setError(errCode)
        ERR_LOG.info(kwargs['api'].strStats())

    if 'gui' in kwargs:
        kwargs['gui'].destroy()

    ERR_LOG.info('Logging Ended')

    if errCode > 0 and 'win' in sys.platform:
        os.startfile(ERR_LOG_FILE)

    sys.exit(errCode)

class DtoolsAPI:
    """
    DtoolsAPI is an object that keeps track of the
    number of api calls made to dtools as well as
    handles the authentication and response parsing
    """
    def __init__(self):
        """
        __init__ is the constructor for the DtoolsAPI
        pulls current API details from file including
        daily pull statistics and authentication info
        """
        self.apiPulls = 0
        self.errState = 0
        self.apiHeader = {}
        self.apiDetails = readFile(API_LOG_FILE)
        if self.apiDetails is None:
            self.apiDetails = {
                'date':datetime.now().strftime('%d/%m/%Y'),
                'totalCalls':0,
                'lastCalls':0
            }
        self.update()
        self.getHeader()

    def getHeader(self):
        """
        getHeader is a function meant to take in sensitive information
        from a file and decode it to be used in DtoolsAPI object

        :return: None
        """
        try:
            with open('AUTHENTICATION', 'r') as file:
                temp = file.read()
        except FileNotFoundError:
            ERR_LOG.critical('Invalid or missing AUTHENTICATION file.')
            safeExit(1)
        auth = json.loads(b64decode(temp.encode()).decode())

        self.apiHeader = {
            'X-API-Key': auth['key'],
            'Authorization': 'Basic ' + b64encode(
                f'{auth['username']}:{auth['password']}'.encode()
            ).decode(),
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

    def setError(self, state):
        """
        setError is a function meant to set the class error flag

        :param state: integer state to set flag to
        """
        self.errState = state

    def getError(self):
        """
        getError is a function meant to get the class error flag

        :return: integer state of the flag
        """
        return self.errState

    def encodeAuth(username, password, apiKey):
        """
        encodeAuth is a function meant to take in sensitive
        information and encode into a file for use later

        :param username: username to store
        :param password: password to store
        :param apiKey: api key to store
        :return: None
        """
        auth = {'username':username, 'password':password, 'key':apiKey}
        temp = b64encode(json.dumps(auth).encode()).decode()
        with open('AUTHENTICATION', 'w') as file:
            file.write(temp)

    def pullData(self, urlTarget):
        """
        pullData is a function meant to take in an api target URL,
        combine with the API_BASE_URL and send am http get request

        :param urlTarget: takes in the api url path to request from,
        appends to API_BASE_URL
        :return: returns the api response data or None
        """
        if self.getTotal() < 10000:
            time.sleep(.75)
            self.apiPulls += 1
            try:
                url = API_URL_BASE + urlTarget
                ERR_LOG.info(f'Pulling api: {urlTarget}')
                response = requests.get(url, headers=self.apiHeader)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                ERR_LOG.warning(f'Error pulling api: {e}')
                return None

    def update(self):
        """
        update is a function meant to store and recall api
        request counts from file

        :return: None
        """
        self.apiDetails['lastCalls'] = self.apiPulls
        today = datetime.now().strftime('%d/%m/%Y')
        if self.apiDetails['date'] == today:
            self.apiDetails['totalCalls'] += self.apiPulls
        else:
            self.apiDetails['date'] = today
            self.apiDetails['totalCalls'] = self.apiPulls
        writeFile(API_LOG_FILE, self.apiDetails)

    def getTotal(self):
        """
        getTotal is a function meant to store and recall api
        request counts from file

        :return: (int) number of calls used today
        """
        return self.apiDetails['totalCalls'] + self.apiPulls

    def getLast(self):
        """
        getLast is a function meant to store and recall api
        request counts from file

        :return: (int) number of calls used last program run
        """
        return self.apiDetails['lastCalls']

    def strStats(self):
        """
        strStats is a function meant to display call data

        :return: (string) number of calls used
        """
        return f'API Calls Used: {self.apiPulls}, ' +\
            f'Total Calls Used Today: {self.apiDetails['totalCalls']}'

def updateTime(allMins, projId, task, quoteMins, taskMins):
    """
    updateTime is a function meant to add time entries to a dictionary

    :param allMins: dictionary to add the time entries too
    :param projId: key to use for the time entry
    :param task: labor type to use for the time entry
    :param taskMins: time in minutes to add to the time entry
    """
    if projId in allMins:
        if task in allMins[projId]:
            allMins[projId][task][0] += quoteMins
            allMins[projId][task][1] += taskMins
        else:
            allMins[projId].update({task:[quoteMins,taskMins]})
        allMins[projId]['TOTALS'][0] += quoteMins
        allMins[projId]['TOTALS'][1] += taskMins
    else:
        allMins.update({projId:{
            task:[quoteMins,taskMins],
            'TOTALS':[quoteMins,taskMins]
        }})

def compileData(api, window, checkBoxes, csvFileName, csvHeaders):
    """
    compileData is the main function meant to send out api requests and
    record/save results to file

    :param api: DtoolsApi object to make calls from
    :param window: tkinter TK() window meant to handle all gui elements
    :param checkBoxes: 4 element list or tuple of booleans for gui
    checkbox states (pullTimeEntries from file, pull job list from file,
    pull job details from file, pull quote details from file)
    :param csvFileName: name of file to store final data
    :return: returns 0 if the function completed properly, 1 if there
    was an issue encountered involving pulling data from files or api
    """
    allMins = {}
    oppList = None

    # Only pull time entry data if a relevant filter is selected
    timeHeaders = ['Labor Type', 'Quoted Minutes', 'Worked Minutes']
    if any(header in csvHeaders for header in timeHeaders):
        timeEntries = None
        # Attempt to pull time entries from saved file
        if checkBoxes[0]:
            timeEntries = readFile(HOURS_FILE + '.txt')

        if timeEntries is None:
            data = api.pullData(API_PATH_TIME)

            if data is not None:
                timeEntries = data['timeEntries']
                writeFile(HOURS_FILE + '.txt', timeEntries)
            else:
                ERR_LOG.error("Unable to retrieve hours data")
                safeExit(1, gui=window, api=api)

        # Store all time data into a dictionary allMins
        for i in range(len(timeEntries)):
            projId = timeEntries[i]['projectId']
            task = timeEntries[i]['laborType']
            taskMins = timeEntries[i]['hoursWorkedInMinutes']

            updateTime(allMins, projId, task, 0, taskMins)
    
    # Load opportunity list, attempt from file
    if checkBoxes[1]:
        oppList = readFile(OPP_FILE + '.txt')

    if oppList is None:
        data = api.pullData(API_PATH_OPP)
        if data is not None:
            oppList = data['opportunities']
            writeFile(OPP_FILE + '.txt', oppList)
        else:
            ERR_LOG.error('Unable to retrieve opportunity list')
            safeExit(1, gui=window, api=api)

    maxItems = len(oppList)
    steps = max(1,int(maxItems/100))
    window.after(0, lambda:
            window.nametowidget('progressLbl').config(text='Processing...')
    )
    # Loop through opportunities, load data 
    for i in range(maxItems):
        if i%steps == 0:
            window.nametowidget('progressBar')['value'] = int(100*i/maxItems)
            window.after(0, lambda:
                window.title(
                    f'D-Tools API Pull (Calls used today: {api.getTotal()}'
                )
            )
        oppId = oppList[i]['id']
        oppStage = oppList[i]['stage']
        oppDetails = None
    
        # Attempt to pull opportunity details from file
        if checkBoxes[2]:
            oppDetails = readFile(DETAILS_PATH+f'/{oppId}.txt')

        if oppDetails is None:
            if oppStage == 'Opportunity Won':
                oppDetails = api.pullData(
                    f'/Projects/GetProject?id={oppId}'
                )
            else:
                oppDetails = api.pullData(
                    f'/Opportunities/GetOpportunity?id={oppId}'
                )

            if oppDetails is not None:
                writeFile(DETAILS_PATH+f'/{oppId}.txt', oppDetails)
            else:
                ERR_LOG.error(f'Unable to retrieve opportunity {oppId}')
                continue

        # Add default filtered data to csv writer list
        csvData = [
            oppDetails[CSV_OPTIONS[i]]
            for i in csvHeaders
            if i not in timeHeaders
        ]

        # Get quoted time if requested in headers
        if any(header in csvHeaders for header in timeHeaders):
            if oppId not in allMins:
                allMins.update({oppId:{'TOTALS':[0,0]}})

            # This is a project with potentially change orders
            if oppStage == 'Opportunity Won':
                # Accumulate all job hours    
                for laborType in oppDetails['laborTypes']:
                    task = laborType['name']
                    taskMins = int(laborType['totalTimeInSeconds']/60)

                    updateTime(allMins, oppId, task, taskMins, 0)

                # Accumulate all change order details
                for changeId in oppDetails['changeOrderIds']:
                    changeDetails = None
                    fileName = CHANGE_PATH+f'/{changeId}.txt'
                    apiPath = f'/ChangeOrders/GetChangeOrder?id={changeId}'

                    # Attempt to pull change order data from file
                    if checkBoxes[4]:
                        changeDetails = readFile(fileName)

                    if changeDetails is None:
                        changeDetails = api.pullData(apiPath)

                        if changeDetails is not None:
                            writeFile(fileName, changeDetails)
                        else:
                            ERR_LOG.warning(f'Cant pull co {changeId}')
                            continue

                    # Only add hours from accepted change orders
                    if changeDetails['state'] == 'Accepted':
                        for laborType in changeDetails['laborTypes']:
                            task = laborType['name']
                            taskMins = int(laborType['totalTimeInSeconds']/60)

                            updateTime(allMins, oppId, task, taskMins, 0)

            # This is an opportunity with quotes, find the biggest
            else:
                oppMinutes = 0
                oppLabor = {}

                for quoteId in oppDetails['quoteIds']:
                    quoteDetails = None
                    fileName = QUOTES_PATH+f'/{quoteId}.txt'
                    apiPath = f'/Quotes/GetQuote?id={quoteId}'

                    # Attempt to pull quote from file
                    if checkBoxes[3]:
                        quoteDetails = readFile(fileName)

                    if quoteDetails is None:
                        quoteDetails = api.pullData(apiPath)

                        if quoteDetails is not None:
                            writeFile(fileName, quoteDetails)
                        else:
                            ERR_LOG.warning(f'Cant pull quote {quoteId}')
                            continue
                    
                    # Comparing to find biggest quote
                    quoteMins = 0
                    quoteLabor = {}
                    for laborType in quoteDetails['laborTypes']:
                        task = laborType['name']
                        taskMins = int(laborType['totalTimeInSeconds']/60)
                        quoteMins += taskMins
                        quoteLabor.update({task:taskMins})
                    if quoteMins > oppMinutes:
                        oppMinutes = quoteMins
                        oppLabor = quoteLabor

                for laborType in oppLabor:
                    allMins.update({oppId:{
                        laborType:[oppLabor[laborType],0],
                        'TOTALS':[oppLabor[laborType],0]
                    }})
        
        # If tracking labor, write to csv file
        if 'Labor Type' in csvHeaders:
            for laborType in allMins[oppId]:
                if laborType != 'TOTALS':
                    temp = csvData + [laborType]
                    if 'Quoted Minutes' in csvHeaders:
                        temp += [allMins[oppId][laborType][0]]
                    if 'Worked Minutes' in csvHeaders:
                        temp += [allMins[oppId][laborType][1]]
                    with open(csvFileName, 'a', newline='') as file:
                        writer = csv.writer(file)
                        writer.writerow(temp)
        else:
            if 'Quoted Minutes' in csvHeaders:
                    csvData += [allMins[oppId]['TOTALS'][0]]
            if 'Worked Minutes' in csvHeaders:
                csvData += [allMins[oppId]['TOTALS'][1]]
            with open(csvFileName, 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(csvData)

    if 'win' in sys.platform:
        os.startfile(csvFileName)
    window.destroy()

def compileDataClicked(api, window, checkBoxes):
    """
    compileDataClicked is the gui hook for the start button that runs
    the main functuion compileData in a thread

    :param window: tkinter TK() window meant to handle all gui elements
    :param checkBoxes: 4 element list or tuple of ttk.Checkbutton
    objects from gui (pullTimeEntries from file, pull job list from
    file, pull job details from file, pull quote details from file)
    :return: None
    """
    keys = list(CSV_OPTIONS.keys())
    selected = window.nametowidget('filterLst').curselection()
    csvHeaders = [keys[i] for i in selected]
    window.nametowidget('startBtn').destroy()

    curTime = datetime.now()
    fileName = CSV_FILE_BASE +\
        '_' + curTime.strftime('%d%B%Y') +\
        '_' + curTime.strftime('%H%M%S') +\
        '.csv'
    with open(fileName, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(csvHeaders)
    Thread(target=lambda: compileData(
                api,
                window,
                [checkBox.state()==('selected',) for checkBox in checkBoxes],
                fileName,
                csvHeaders
            ),
        daemon=True
    ).start()

def filterClicked(window):
    """
    filterClicked is the gui hook toggle for the filterLst dropdown to let
    the user multiselect csv data fields to output

    :param window: tkinter TK() window meant to handle all gui elements
    :return: None
    """
    if window.nametowidget('filterLst').winfo_ismapped() > 0:
        window.nametowidget('filterLst').place_forget()
    else:
        window.nametowidget('filterLst').place(relx=.5, y=40,
            anchor='n', width=150, height=250)
        window.nametowidget('filterLst').lift()

def windowClosed():
    """
    windowClosed is the gui hook for if the gui is manually closed or
    terminated, will terminate program and all threads

    :param window: tkinter TK() window meant to handle all gui elements
    :return: None
    """
    ERR_LOG.error('Window force closed')
    safeExit(1)

def main():
    """
    main is the entrance point for the program and creates/runs the gui
    file and records api connection statistics

    :return: None
    """
    logging.basicConfig(
        filename=ERR_LOG_FILE,
        format='%(asctime)s-%(levelname)s-%(message)s',
        level=logging.INFO,
        filemode='w',
        force=True
    )
    ERR_LOG.info('Logging Started')

    makedirs(DETAILS_PATH, exist_ok=True)
    makedirs(QUOTES_PATH, exist_ok=True)
    makedirs(CHANGE_PATH, exist_ok=True)

    api = DtoolsAPI()

    # create GUI elements
    window = tk.Tk()
    window.protocol('WM_DELETE_WINDOW', windowClosed)
    window.title('D-Tools API Pull (Calls used today: ' +\
        f'{api.getTotal()}/10000, Estimated new calls: ' +\
        f'{max(api.getLast(),300)})'
    )
    window.geometry('600x330')
    window.minsize(600,330)
    checkBoxes = [
        ttk.Checkbutton(text='Attempt to pull hours from file'),
        ttk.Checkbutton(text='Attempt to pull opportunity list from file'),
        ttk.Checkbutton(text='Attempt to pull opportunity details from file'),
        ttk.Checkbutton(text='Attempt to pull quote details from file'),
        ttk.Checkbutton(text='Attempt to pull change order details from file')
    ]
    for checkBox in checkBoxes:
        checkBox.invoke()
        yPos = 50 + 30*checkBoxes.index(checkBox)
        checkBox.place(relx=.5, y=yPos, anchor='n', height=30)
    progressBar = ttk.Progressbar(name='progressBar')
    progressBar.place(relx=.5, y=250, anchor='n', height=30, width=590)
    progressLabel = tk.Label(name='progressLbl', text='Paused',)
    progressLabel.place(relx=.5, y=290, anchor='n', height=30)
    filterOptions = tk.Listbox(name='filterLst', selectmode='multiple')
    filterOptions.insert(tk.END, *CSV_OPTIONS)
    filterOptions.select_set(0,tk.END)
    filterButton = ttk.Button(name='filterBtn',
        text='CSV Fields',
        command=lambda: filterClicked(window))
    filterButton.place(relx=.5, y=10, anchor='n', width=100, height=30)
    startButton = ttk.Button(name='startBtn',
        text='Start Collecting Data',
        command=lambda: compileDataClicked(api, window, checkBoxes))
    startButton.place(relx=.5, y=210, anchor='n', width=200, height=30)

    window.mainloop()

    api.update()
    safeExit(api.getError(), api=api)

if __name__ == '__main__':
    main()
    ERR_LOG.info('Logging Ended')