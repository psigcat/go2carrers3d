"""  
/***************************************************************************
go2carrers3d
                                 A QGIS plugin

                             -------------------
        begin                :
        copyright            :
        email                :
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from PyQt5 import Qt, QtCore, QtWidgets, QtGui, uic
from qgis import core, utils, gui

import json
import os
#import html.parser as HTMLParser
import html
import xml.sax.saxutils
import resources_rc

MAIN_DIALOG_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ui_go2carrers3d.ui'))

DUM_DIALOG_CLASS, _ = uic.loadUiType(os.path.join(
    os.path.dirname(__file__), 'ui_go2carrers3dDum.ui'))


# create the view dialog
class go2carrers3dDialog(QtWidgets.QDockWidget, MAIN_DIALOG_CLASS):

    focus_in = QtCore.pyqtSignal(int, name='focusIn')
    closed_ev = QtCore.pyqtSignal(int, name='closed')
    resized_ev = QtCore.pyqtSignal(int, name='resized')
    enter_ev = QtCore.pyqtSignal(int, name='enter')

    def __init__(self):
        QtWidgets.QDialog.__init__(self)
        self.setupUi(self)

    def closeEvent(self, event):
        print("closed")
        self.closed_ev.emit(1)

    def resizeEvent (self, event):
        print("resized")
        self.resized_ev.emit(1)

    def enterEvent (self,event):
        print("entered")
        self.enter_ev.emit(1)

# create the dummy widget
class dumWidget(QtWidgets.QDialog, DUM_DIALOG_CLASS):

    enter_ev = QtCore.pyqtSignal(int, name='enter')

    def __init__(self):
        QtWidgets.QDialog.__init__(self)
        self.setupUi(self)

    def enterEvent (self,event):
        self.enter_ev.emit(1)
