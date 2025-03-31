"""
File: Dtools_Data_Pull.py
Associated Files: AUTHENTICATION, LICENSE, config.json
Required Packages: requests 
License: Apache-2.0
Date Created: 18Feb2025
Last Modified: 31Mar2025 by John Lukowski

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
__version__ = '1.1'
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
from copy import copy, deepcopy
from threading import Thread
from datetime import datetime

### 3rd Party Imports
import requests # pip install requests

### Static Variables
CONFIG_FILE = 'config.json'
ERR_LOG_FILE = 'Dtools.log'

# Start an error logger for important steps and errors
ERR_LOG = logging.getLogger(__name__)
logging.basicConfig(
        filename=ERR_LOG_FILE,
        format='%(asctime)s-%(levelname)s-%(message)s',
        level=logging.INFO,
        filemode='w',
        force=True
    )
ERR_LOG.info('Logging Started')

def readConfig(fileName):
    """
    readConfig is a function meant to read config variables
    from a json formatted file

    :param fileName: string path/name of the config file
    """
    try:
        with open(fileName, 'r') as file:
            data = json.load(file)
    except Exception as e:
        ERR_LOG.warning(f'File read error: {fileName}: {str(e)}')
        safeExit(1)
    for key, value in data.items():
        globals()[key] = value

def writeFile(fileName, data):
    """
    writeFile is a function meant write given data
    to a given file

    :param fileName: string path/name of the file
    :param data: string data to write to file
    """
    try:
        with open(fileName, 'w') as file:
            json.dump(data, file)
    except Exception as e:
        ERR_LOG.warning(f'File write error: {fileName}: {str(e)}')

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
        ERR_LOG.warning(f'File read error: {fileName}: {str(e)}')
        return None

def safeExit(errCode, *args, **kwargs):
    """
    safeExit is a function meant to end the program
    and show the error log if not exited with errCode 0
    Will handle closing the tkinter window if open

    :param errCode: flag for error, 0 no error or 1 error
    :param kwargs: optional 'api' and 'gui' objects
    """
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
        """
        try:
            with open('AUTHENTICATION', 'r') as file:
                temp = file.read()
        except FileNotFoundError:
            ERR_LOG.critical('Invalid or missing AUTHENTICATION file.')
            safeExit(1)
        try:
            auth = json.loads(b64decode(temp.encode()).decode())
        except Exception as e:
            ERR_LOG.warning(f'Invalid AUTHENTICATION file: {str(e)}')
            safeExit(1)

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
            time.sleep(API_DELAY/1000)
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
    :param quoteMins: time in minutes to add to the time entry
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
    """
    allMins = {}
    allService = {}
    oppList = None
    csvWriteQueue = []

    timeHeaders = ['Labor Type', 'Quoted Minutes', 'Worked Minutes']
    serviceHeaders = ['Service Type', 'Service Quantity', 'Service Price']

    # Only pull time entry data if a relevant filter is selected
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
                    f'D-Tools API Pull (Calls used today: {api.getTotal()})'
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
            if i not in timeHeaders+serviceHeaders
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
                        oppLabor = deepcopy(quoteLabor)

                for laborType in oppLabor:
                    allMins.update({oppId:{
                        laborType:[oppLabor[laborType],0],
                        'TOTALS':[oppLabor[laborType],0]
                    }})

        # Get service plans if requested in headers
        if any(header in csvHeaders for header in serviceHeaders):
            if oppId not in allService:
                allService.update({oppId:{'TOTALS':[0,0]}})

            # This is a project with potentially change orders
            if oppStage == 'Opportunity Won' and 'items' in oppDetails:
                # Accumulate all service items
                for item in oppDetails['items']:
                    if item['category'] == SERVICE_CATEGORY:
                        name = item['name']
                        quant = item['quantity']
                        price = 0
                        if item['msrp'] is not None:
                            price += item['msrp'] * quant
                        if item['laborItems'] is not None:
                            price += quant * sum(i['price']
                                for i in item['laborItems']
                            )

                        updateTime(allService, oppId, name, quant, price)

                # Accumulate all change order details
                for changeId in oppDetails['changeOrderIds']:
                    changeDetails = readFile(CHANGE_PATH+f'/{changeId}.txt')
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
                        for item in changeDetails['items']:
                            if item['category'] == SERVICE_CATEGORY:
                                name = item['name']
                                quant = item['quantity']
                                price = 0
                                if item['msrp'] is not None:
                                    price += item['msrp'] * quant
                                if item['laborItems'] is not None:
                                    price += quant * sum(i['price']
                                        for i in item['laborItems']
                                    )

                                updateTime(allService, oppId, name, quant, price)

            # This is an opportunity with quotes, find the biggest
            else:
                oppPrice = 0
                oppService = {}

                for quoteId in oppDetails['quoteIds']:
                    quoteDetails = None
                    fileName = QUOTES_PATH+f'/{quoteId}.txt'
                    apiPath = f'/Quotes/GetQuote?id={quoteId}'

                    # Attempt to pull quote from file
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
                    quotePrice = 0
                    quoteService = {}
                    for item in quoteDetails['items']:
                        if item['category'] == SERVICE_CATEGORY:
                            name = item['name']
                            quant = item['quantity']
                            price = 0
                            if item['msrp'] is not None:
                                price += item['msrp'] * quant
                            if item['laborItems'] is not None:
                                price += quant * sum(i['price']
                                    for i in item['laborItems']
                                )
                            quotePrice += price
                            if name in quoteService:
                                quoteService[name][0] += quant
                                quoteService[name][1] += price
                            else:
                                quoteService.update({name:[quant,price]})
                    if quotePrice > oppPrice:
                        oppPrice = quotePrice
                        oppService = deepcopy(quoteService)

                for item in oppService:
                    quant = oppService[item][0]
                    price = oppService[item][1]
                    updateTime(allService, oppId, item, quant, price)
        
        # If tracking labor or service, write to csv file
        if 'Labor Type' in csvHeaders:
            for laborType in allMins[oppId]:
                if laborType != 'TOTALS':
                    temp = copy(csvData) + [laborType]
                    if 'Quoted Minutes' in csvHeaders:
                        temp += [allMins[oppId][laborType][0]]
                    if 'Worked Minutes' in csvHeaders:
                        temp += [allMins[oppId][laborType][1]]
                    if 'Service Quantity' in csvHeaders:
                        temp += [allService[oppId]['TOTALS'][0]]
                    if 'Service Price' in csvHeaders:
                        temp += [allService[oppId]['TOTALS'][1]]
                    csvWriteQueue += [temp]
        elif 'Service Type' in csvHeaders:
            for serviceType in allService[oppId]:
                if serviceType != 'TOTALS':
                    temp = copy(csvData)
                    if 'Quoted Minutes' in csvHeaders:
                        temp += [allMins[oppId]['TOTALS'][0]]
                    if 'Worked Minutes' in csvHeaders:
                        temp += [allMins[oppId]['TOTALS'][1]]
                    temp += [serviceType]
                    if 'Service Quantity' in csvHeaders:
                        temp += [allService[oppId][serviceType][0]]
                    if 'Service Price' in csvHeaders:
                        temp += [allService[oppId][serviceType][1]]
                    csvWriteQueue += [temp]
        else:
            if 'Quoted Minutes' in csvHeaders:
                csvData += [allMins[oppId]['TOTALS'][0]]
            if 'Worked Minutes' in csvHeaders:
                csvData += [allMins[oppId]['TOTALS'][1]]
            if 'Service Quantity' in csvHeaders:
                csvData += [allService[oppId]['TOTALS'][0]]
            if 'Service Price' in csvHeaders:
                csvData += [allService[oppId]['TOTALS'][1]]
            csvWriteQueue += [csvData]

    with open(csvFileName, 'a', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(csvWriteQueue)

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
    """
    if window.nametowidget('filterLst').winfo_ismapped() > 0:
        window.nametowidget('filterLst').place_forget()
    else:
        window.nametowidget('filterLst').place(relx=.5, y=40,
            anchor='n', width=150, height=250)
        window.nametowidget('filterLst').lift()

def filterSelection(event, box):
    """
    filterSelection is the gui hook for a listbox click event
    used to only allow selecting one Type field per run

    :param event: tkinter builtin event object
    :param box: the listbox object triggering the event
    """
    selected = box.get(box.nearest(event.y))
    if 'Service Type' in selected:
        box.selection_clear(list(CSV_OPTIONS.keys()).index('Labor Type'))
    elif 'Labor Type' in selected:
        box.selection_clear(list(CSV_OPTIONS.keys()).index('Service Type'))

def windowClosed():
    """
    windowClosed is the gui hook for if the gui is manually closed or
    terminated, will terminate program and all threads
    """
    ERR_LOG.error('Window force closed')
    safeExit(1)

def main():
    """
    main is the entrance point for the program and creates/runs the gui
    file and records api connection statistics
    """
    readConfig(CONFIG_FILE)

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
    filterOptions.select_set(0,list(CSV_OPTIONS.keys()).index('Labor Type')-1)
    filterOptions.bind('<Button-1>', lambda event: filterSelection(event, filterOptions))
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