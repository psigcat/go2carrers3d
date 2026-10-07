"""
/***************************************************************************
 go2carrers3d
                                 A QGIS plugin
                              -------------------
        begin                : 2014-03-29
        copyright            : (C) 2014 enrico ferreguti
        email                : enricofer@gmail.com
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
from qgis.PyQt.QtWidgets import QApplication
from PyQt5 import Qt, QtCore, QtWidgets, QtGui, QtWebEngineWidgets, QtXml, QtNetwork, uic
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtCore import QSettings, qVersion, QCoreApplication, Qt
from PyQt5.QtCore import pyqtSlot
from qgis import core, utils, gui
from qgis.utils import iface, qgsfunction, plugins
from string import digits
from .go2carrers3dDialog import go2carrers3dDialog, dumWidget
from .transformgeom import transformGeometry

import webbrowser
import tempfile
import os
import math
import time
import json
import configparser
import sip
import pathlib  
import datetime
import re

DEBUG_PORT = '5588'
DEBUG_URL = 'http://127.0.0.1:%s' % DEBUG_PORT
os.environ['QTWEBENGINE_REMOTE_DEBUGGING'] = DEBUG_PORT

H_SV_CAMERA = 2.7


class go2carrers3d(gui.QgsMapTool):

    def __init__(self, iface):

       # Save reference to the QGIS interface
        self.iface = iface
        # reference to the canvas
        self.canvas = self.iface.mapCanvas()
        self.plugin_dir = os.path.dirname(__file__)
        pluginMetadata = configparser.ConfigParser()
        pluginMetadata.read(os.path.join(self.plugin_dir , 'metadata.txt'))
        self.version = pluginMetadata.get('general', 'version')

        # initialize locale
        locale = QSettings().value('locale/userLocale')[0:2]
        locale_path = os.path.join(
            self.plugin_dir,
            'i18n',
            'go2carrers3d_{}.qm'.format(locale))

        gui.QgsMapTool.__init__(self, self.canvas)
        self.S = QtCore.QSettings()

    def tr(self, message):  # pylint: disable=no-self-use
        """Get the translation for a string using Qt translation API.

        We implement this ourselves since we do not inherit QObject.

        :param message: String for translation.
        :type message: str, QString

        :returns: Translated version of message.
        :rtype: QString
        """
        # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
        return QCoreApplication.translate('go2carrers3d', message)

    def initGui(self):
        # Create actions that will start plugin configuration
        self.StreetviewAction = QtWidgets.QAction(QtGui.QIcon(os.path.join(os.path.dirname(__file__), 'res', 'icoStreetview.png')), \
            self.tr("Click to open Carrers"), self.iface.mainWindow())
        #self.StreetviewAction = QtWidgets.QAction(QtGui.QIcon(":/plugins/go2carrers3d/res/icoStreetview.png"), \
        #    "Click to open Google Street View", self.iface.mainWindow())
        self.StreetviewAction.triggered.connect(self.StreetviewRun)
        # Add toolbar button and menu item
        self.iface.addToolBarIcon(self.StreetviewAction)
        self.iface.addPluginToWebMenu(self.tr("&go2carrers3d"), self.StreetviewAction)
        self.dirPath = os.path.dirname( os.path.abspath( __file__ ) )
        self.actualPOV = {}
        self.view = go2carrers3dDialog()
        self.dumView = dumWidget()
        self.dumView.enter.connect(self.clickOn)
        self.dumView.iconRif.setPixmap(QtGui.QPixmap(os.path.join(os.path.dirname(__file__), 'res', 'icoStreetview.png')))
        #self.dumView.iconRif.setPixmap(QtGui.QPixmap(":/plugins/go2carrers3d/res/icoStreetview.png"))
        self.apdockwidget=QtWidgets.QDockWidget(self.tr("go2carrers3d") , self.iface.mainWindow() )
        #self.apdockwidget.
        self.apdockwidget.setObjectName("go2carrers3d")
        self.apdockwidget.setWidget(self.dumView)
        self.iface.addDockWidget( QtCore.Qt.LeftDockWidgetArea, self.apdockwidget)
        self.apdockwidget.update()

        self.viewHeight=self.apdockwidget.size().height()
        self.viewWidth=self.apdockwidget.size().width()

        self.channel = QWebChannel()
        self.channel.registerObject('backend', self)
        self.view.SV.page().setWebChannel(self.channel)
        self.view.BE.page().setWebChannel(self.channel)
        

        self.view.SV.settings().setAttribute(QtWebEngineWidgets.QWebEngineSettings.JavascriptEnabled, True)
        self.view.SV.settings().setAttribute(QtWebEngineWidgets.QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.view.SV.settings().setAttribute(QtWebEngineWidgets.QWebEngineSettings.ErrorPageEnabled, True)
        self.view.SV.settings().setAttribute(QtWebEngineWidgets.QWebEngineSettings.PluginsEnabled, True)

        self.view.BE.settings().setAttribute(QtWebEngineWidgets.QWebEngineSettings.JavascriptEnabled, True)
        self.view.BE.settings().setAttribute(QtWebEngineWidgets.QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        self.view.BE.settings().setAttribute(QtWebEngineWidgets.QWebEngineSettings.ErrorPageEnabled, True)
        self.view.BE.settings().setAttribute(QtWebEngineWidgets.QWebEngineSettings.PluginsEnabled, True)

        self.view.SV.loadFinished.connect(self.handleLoaded)

        self.view.enter.connect(self.clickOn)
        self.view.closed.connect(self.closeDialog)
        self.setButtonBarSignals()
        self.apdockwidget.visibilityChanged.connect(self.apdockChangeVisibility)
        self.pressed=None
        self.CTRLPressed=None

        self.controlShape = gui.QgsRubberBand(self.iface.mapCanvas(),core.QgsWkbTypes.LineGeometry )
        self.controlShape.setWidth( 1 )
        self.position=gui.QgsRubberBand(self.iface.mapCanvas(),core.QgsWkbTypes.PointGeometry )
        self.position.setWidth( 5 )
        self.position.setIcon(gui.QgsRubberBand.ICON_CIRCLE)
        self.position.setIconSize(6)
        self.position.setColor(QtCore.Qt.red)
        self.aperture=gui.QgsRubberBand(self.iface.mapCanvas(),core.QgsWkbTypes.LineGeometry )

        self.digitizePosition=gui.QgsRubberBand(self.iface.mapCanvas(),core.QgsWkbTypes.PointGeometry )
        self.digitizePosition.setIcon(gui.QgsRubberBand.ICON_CIRCLE)
        self.digitizePosition.setIconSize(6)
        self.digitizePosition.setColor(QtCore.Qt.green)

        self.rotateTool = transformGeometry()
        self.canvas.rotationChanged.connect(self.mapRotationChanged)
        self.canvas.scaleChanged.connect(self.setPosition)
        self.dumLayer = core.QgsVectorLayer("Point?crs=EPSG:4326", "temporary_points", "memory")
        self.actualPOV = {"lat":0.0,"lon":0.0,"heading":0.0,"zoom":1,"pitch":0}
        self.pointWgs84 = None
        self.httpConnecting = None

        # Initialize a timer to poll the Carrers 3D URL for coordinate/heading changes
        self.syncTimer = QtCore.QTimer(self.iface.mainWindow())
        self.syncTimer.setInterval(250) # Check every 250 milliseconds
        self.syncTimer.timeout.connect(self.pollCarrers3D)

        # print("zoomToCoverageAction")
        # self.zoomToCoverageAction()

    def handleLoaded(self, ok):
        if ok:
            # JavaScript to automatically dismiss modals and hide the 2D map
            js_code = """
            // 1. Try to find and click the accept/close button on the modal
            var buttons = document.querySelectorAll('button');
            buttons.forEach(function(btn) {
                var text = btn.innerText.toLowerCase();
                if (text.includes('acceptar') || text.includes('close') || text.includes('d\\'acord') || text.includes('entès')) {
                    btn.click();
                }
            });
            
            // 2. Force-remove any remaining modal dialogs and dark background overlays
            var elementsToRemove = document.querySelectorAll('.v-dialog__content, .v-overlay, .modal, .modal-backdrop');
            elementsToRemove.forEach(function(el) { 
                el.style.display = 'none'; 
                el.remove(); 
            });
            
            // 3. Hide the 2D map pane to make the Panorama view fullscreen
            // MapiaStreets uses 'splitpanes' for the layout
            var panes = document.querySelectorAll('.splitpanes__pane');
            if (panes.length > 1) {
                panes[0].style.display = 'none'; // Hides the map
                panes[1].style.width = '100%';   // Expands the panorama
            }
            """
            
            # Execute the script in the QGIS web viewer
            self.view.SV.page().runJavaScript(js_code)
            
            # (Optional) If you want the web inspector for debugging, keep this:
            # self.view.SV.page().setDevToolsPage(self.inspector.page())
            # self.inspector.show()

    def setButtonBarSignals(self):
        #contextMenu
        contextMenu = QtWidgets.QMenu()
        self.openInBrowserItem = contextMenu.addAction(QtGui.QIcon(os.path.join(self.dirPath,"res","browser.png")),self.tr("Open in external browser"))
        self.openInBrowserItem.triggered.connect(self.openInBrowserAction)
        # self.takeSnapshopItem = contextMenu.addAction(QtGui.QIcon(os.path.join(self.dirPath,"res","images.png")),self.tr("Take a panorama snaphot"))
        # self.takeSnapshopItem.triggered.connect(self.takeSnapshopAction)
        self.digitizeItem = contextMenu.addAction(QtGui.QIcon(os.path.join(self.dirPath,"res","marker_green.png")),self.tr("Digitize"))
        self.digitizeItem.triggered.connect(self.digitizeAction)
        contextMenu.addSeparator()
        
        optionsMenu = contextMenu.addMenu(self.tr("Options"))
        self.showCoverage = optionsMenu.addAction(self.tr("Show Carrers 3D coverage"))
        self.showCoverage.setCheckable(True)
        self.showCoverage.setChecked(False)
        self.zoomToCoverage = optionsMenu.addAction(self.tr("Zoom to coverage"))
        self.zoomToCoverage.triggered.connect(self.zoomToCoverageAction)        
        optionsMenu.addSeparator()

        self.showCoverage.toggled.connect(self.showCoverageLayer)
        contextMenu.addSeparator()
        self.showWebInspector = contextMenu.addAction(self.tr("Show web inspector for debugging"))
        self.showWebInspector.triggered.connect(self.showWebInspectorAction)
        self.view.btnMenu.setIcon(QtGui.QIcon(os.path.join(self.dirPath,"res","down.png")))
        self.view.btnMenu.setMenu(contextMenu)
        self.view.btnMenu.setPopupMode(QtWidgets.QToolButton.InstantPopup)


    def showWebInspectorAction(self):
        self.inspector = QWebEngineView()
        self.inspector.setWindowTitle('Web Inspector')
        self.inspector.load(QtCore.QUrl(DEBUG_URL))
        if self.view.SV.isVisible():
            self.view.SV.page().setDevToolsPage(self.inspector.page())
        else:
            self.view.BE.page().setDevToolsPage(self.inspector.page())
        self.inspector.show()
        self.inspector.raise_()


    def showCoverageLayer(self): 
        if self.showCoverage.isChecked():
            # Use the Carrers 3D XYZ tile URL
            service_url = "https://visors.icgc.cat/apps/giscube-admin/qgisserver/services/ubicacio-captures/tilecache/{z}/{x}/{y}.png"
            service_uri = f"type=xyz&zmin=0&zmax=21&url={service_url}"
            
            # Create the raster layer
            layer = core.QgsRasterLayer(service_uri, "Carrers 3D coverage", "wms")
            self.coverageLayerId = layer.id()
            
            # Add to project and move to the bottom/top of the Table of Contents
            core.QgsProject.instance().addMapLayer(layer, False)
            toc_root = core.QgsProject.instance().layerTreeRoot()
            toc_root.insertLayer(0, layer)
        else:
            try:
                core.QgsProject.instance().removeMapLayer(self.coverageLayerId)
            except:
                pass

    def zoomToCoverageAction(self):
        """Zooms the QGIS map canvas to the approximate bounding box of Catalunya."""
        # Define Catalunya's bounding box in EPSG:4326 (WGS 84)
        # Xmin (Lon), Ymin (Lat), Xmax (Lon), Ymax (Lat)
        rect_wgs84 = core.QgsRectangle(0.15, 40.51, 3.33, 42.86)
        
        # Get the current Coordinate Reference Systems
        crsSrc = core.QgsCoordinateReferenceSystem("EPSG:4326")
        crsDest = self.iface.mapCanvas().mapSettings().destinationCrs()
        
        # Create a transform object to translate the coordinates to the map's current CRS
        xform = core.QgsCoordinateTransform(crsSrc, crsDest, core.QgsProject.instance())
        
        # Transform the bounding box and apply it to the canvas
        rect_canvas = xform.transformBoundingBox(rect_wgs84)
        self.iface.mapCanvas().setExtent(rect_canvas)
        self.iface.mapCanvas().refresh()

    def scanForCoverageLayer(self):
        return
        #used for catching coverage layer if saved along with projectS
        for layer_id,layer in core.QgsProject.instance().mapLayers().items():
            if layer.type() == core.QgsMapLayer.PluginLayer and layer.id()[:19] == "Streetview_coverage":
                self.showCoverage.blockSignals ( True )
                self.showCoverage.setChecked(True)
                self.showCoverage.blockSignals ( False )
                self.coverageLayerId = layer.id()

    def mapRotationChanged(self,r):
        #unused landing method for rotationChanged signal.
        return

    def getNearestSVLocation(self,lon,lat):
        js = "this.getNearestSVLocation(%f,%f)" %(lon,lat)
        if not self.pointWgs84:
            self.pointWgs84 = core.QgsPointXY(lon,lat)
            self.heading = 0
            self.StreetviewRun()
            self.openSVDialog()
            time.sleep(1)
            self.StreetviewRun()
            delay = 4
        else:
            delay = 4

        self.SVLocationResponse = None
        start = datetime.datetime.now()
        timeout = False
        while not (self.SVLocationResponse or timeout):
            time.sleep(0.2)
            tdiff = datetime.datetime.now()-start
            QtWidgets.QApplication.processEvents()
            if tdiff.seconds > delay:
                timeout = True
        return self.SVLocationResponse


    def aboutAction(self):
        self.licenceDlg.show()

    def switchViewAction(self):
        if self.view.SV.isVisible():
            self.switch2BE()
        else:
            self.switch2SV()

    def openInBrowserAction(self):
        if self.view.SV.isVisible():
            self.openInBrowserSV()
        else:
            self.openInBrowserBE()

    def digitizeAction(self):
        self.takeSnapshotSV(type="digitize")

    def unload(self):
        self.syncTimer.stop()
        self.disableControlShape()
        try:
            core.QgsProject.instance().removeMapLayer(self.coverageLayerId)
        except:
            pass
        #Remove the plugin menu item and icon and dock Widget
        try:
            self.iface.projectRead.disconnect(self.projectReadAction)
        except:
            pass
        try:
            self.canvas.rotationChanged.disconnect(self.mapRotationChanged)
        except:
            pass
        try:
            self.canvas.scaleChanged.disconnect(self.setPosition)
        except:
            pass
        try:
            self.position.reset()
        except:
            pass
        try:
            self.digitizePosition.reset()
        except:
            pass
        try:
            self.aperture.reset()
        except:
            pass
        self.iface.removePluginMenu("&go2carrers3d",self.StreetviewAction)
        self.iface.removeToolBarIcon(self.StreetviewAction)
        self.iface.removeDockWidget(self.apdockwidget)

        self.showCoverage.setChecked(False)

        # core.QgsExpression.unregisterFunction('get_carrers3d_pov')
        # core.QgsExpression.unregisterFunction('get_carrers3d_url')

    @pyqtSlot(str)
    def catchJSevents(self,status):
        print ("catchJSevents", status)
        try:
            tmpPOV = json.JSONDecoder().decode(status)
        except:
            tmpPOV = None
        if tmpPOV:
            if tmpPOV["transport"] == "drag":
                self.refreshWidget(tmpPOV['lon'], tmpPOV['lat'])
            elif tmpPOV["transport"] == "view":
                self.httpConnecting = True
                if self.actualPOV["lat"] != tmpPOV["lat"] or self.actualPOV["lon"] != tmpPOV["lon"]:
                    self.actualPOV = tmpPOV
                    actualPoint = core.QgsPointXY(float(self.actualPOV['lon']),float(self.actualPOV['lat']))
                else:
                    self.actualPOV = tmpPOV
                self.setPosition()
            elif tmpPOV["transport"] == "SVLocation":
                if tmpPOV["status"] == 'OK':
                    self.SVLocationResponse = core.QgsPointXY(tmpPOV["lon"],tmpPOV["lat"])
                else:
                    self.SVLocationResponse = None #core.QgsPointXY()


    def pollCarrers3D(self):
        """Requests the current URL from the web engine."""
        if self.view.SV.isVisible():
            self.view.SV.page().runJavaScript("window.location.href", self.processUrl)

    def processUrl(self, url_str):
        """Parses the URL to extract lat, lon, and heading, and updates the QGIS map."""
        if not url_str: 
            return
            
        # MapiaStreets format: /mapiastreets/lat,lon/heading/
        match = re.search(r'mapiastreets/([\d\.\-]+),([\d\.\-]+)/([\d\.\-]+)', url_str)
        if match:
            lat = float(match.group(1))
            lon = float(match.group(2))
            heading = float(match.group(3))
        else:
            return # URL format doesn't match, do nothing

        # Only update if the camera actually moved to avoid jitter
        if (self.actualPOV.get('lat') == lat and 
            self.actualPOV.get('lon') == lon and 
            self.actualPOV.get('heading') == heading):
            return

        # Format the data exactly how the original plugin expects it
        tmpPOV = {
            "transport": "view",
            "lat": lat,
            "lon": lon,
            "heading": heading,
            "zoom": 1,
            "pitch": 0
        }
        
        # Feed it into the original logic to move the QGIS marker and cone!
        self.catchJSevents(json.dumps(tmpPOV))


    def setPosition(self,forcePosition = None):
        #if self.apdockwidget.widget().__dict__ == self.dumView.__dict__ or not self.apdockwidget.isVisible():
        if not self.apdockwidget.isVisible():
          return
        
        try:
            actualWGS84 = core.QgsPointXY (float(self.actualPOV['lon']),float(self.actualPOV['lat']))
        except:
            return
        
        actualSRS = self.transformToCurrentSRS(actualWGS84)
        self.position.reset()
        self.position=gui.QgsRubberBand(self.iface.mapCanvas(),core.QgsWkbTypes.PointGeometry )
        self.position.setWidth( 4 )
        self.position.setIcon(gui.QgsRubberBand.ICON_CIRCLE)
        self.position.setIconSize(4)
        self.position.setColor(QtCore.Qt.blue)
        self.position.addPoint(actualSRS)
        CS = self.canvas.mapUnitsPerPixel()*25
        zoom = float(self.actualPOV['zoom'])
        fov = (3.9018*pow(zoom,2) - 42.432*zoom + 123)/100;
        A1x = actualSRS.x()-CS*math.cos(math.pi/2-fov)
        A2x = actualSRS.x()+CS*math.cos(math.pi/2-fov)
        A1y = actualSRS.y()+CS*math.sin(math.pi/2-fov)
        A2y = A1y

        self.aperture.reset()
        self.aperture=gui.QgsRubberBand(self.iface.mapCanvas(),core.QgsWkbTypes.LineGeometry )
        self.aperture.setWidth( 3 )
        self.aperture.setColor(QtCore.Qt.blue)
        self.aperture.addPoint(core.QgsPointXY(A1x,A1y))
        self.aperture.addPoint(actualSRS)
        self.aperture.addPoint(core.QgsPointXY(A2x,A2y))

        angle = float(self.actualPOV['heading'])*math.pi/-180
        self.aperture.setToGeometry(self.rotateTool.rotate(self.aperture.asGeometry(),actualSRS,angle))
        
        a = math.radians(90 + self.actualPOV.get('pitch',0))
        POV_distance = H_SV_CAMERA/math.cos(a)*math.sin(a)
        self.digitizePosition.reset()
        if POV_distance >0 and POV_distance < 50:
            self.digitizePosition=gui.QgsRubberBand(self.iface.mapCanvas(),core.QgsWkbTypes.PointGeometry )
            self.digitizePosition.setIcon(gui.QgsRubberBand.ICON_CIRCLE)
            self.digitizePosition.setIconSize(6)
            self.digitizePosition.setColor(QtCore.Qt.green)
            self.digitizePosition.addPoint(core.QgsPointXY(actualSRS.x(),actualSRS.y()+POV_distance))
            self.digitizePosition.setToGeometry(self.rotateTool.rotate(self.digitizePosition.asGeometry(),actualSRS,angle))
            dlonlat = self.transformToWGS84(self.digitizePosition.asGeometry().asPoint())
            self.actualPOV['dlon'] = dlonlat.x()
            self.actualPOV['dlat'] = dlonlat.y()
            self.view.SV.page().runJavaScript("this.enableDigitizeCursor(true)")
            self.digitizeItem.setEnabled(True)
        else:
            self.actualPOV['dlon'] = None
            self.actualPOV['dlat'] = None
            self.view.SV.page().runJavaScript("this.enableDigitizeCursor(false)")
            self.digitizeItem.setEnabled(False)


    def closeDialog(self):
        self.position.reset()
        self.aperture.reset()
        self.syncTimer.stop()

    def apdockChangeVisibility(self,vis):
        if not vis:
            self.position.reset()
            self.aperture.reset()
            self.disableControlShape()
            self.syncTimer.stop()
            try:
                self.StreetviewAction.setIcon(QtGui.QIcon(os.path.join(os.path.dirname(__file__), 'res', 'icoStreetview_gray.png')))
            except:
                pass

        else:
            self.StreetviewAction.setEnabled(True)
            self.syncTimer.start()
            self.StreetviewAction.setIcon(QtGui.QIcon(os.path.join(os.path.dirname(__file__), 'res', 'icoStreetview.png')))
            self.setPosition()

    def resizeStreetview(self):
        print("resizeStreetview")
        #self.resizing = True
        self.resizeWidget()
        try:
            self.view.SV.loadFinished.connect(self.endRefreshWidget)
            self.refreshWidget(self.pointWgs84.x(), self.pointWgs84.y())
        except:
            pass

    def refreshWidget(self, new_lon, new_lat):
        if self.actualPOV['lat'] != 0.0:
            route = f"#/info/mapiastreets/{new_lat},{new_lon}/{self.heading}/"
            self.gswDialogUrl = f"https://visors.icgc.cat/catalunya-digital/carrers-3d/{route}"
            self.view.SV.setUrl(QtCore.QUrl(self.gswDialogUrl))

    def endRefreshWidget(self):
        print("endRefreshWidget")
        self.view.SV.loadFinished.disconnect()
        self.refreshWidget(self.pointWgs84.x(), self.pointWgs84.y())

    def clickOn(self):
        self.explore()

    def resizeWidget(self):
        print("resizeWidget")
        self.viewHeight=self.view.size().height()
        self.viewWidth=self.view.size().width()
        self.view.SV.resize(self.viewWidth,self.viewHeight)
        self.view.BE.resize(self.viewWidth,self.viewHeight)
        self.view.buttonBar.move(self.viewWidth-252,0)

    def switch2BE(self):
        # Procedure to operate switch to google maps dialog set
        self.view.BE.show()
        self.view.SV.hide()
        #self.view.btnSwitchView.setIcon(QtGui.QIcon(os.path.join(self.dirPath, "res", "icoStreetview.png")))
        #self.view.btnPrint.setDisabled(True)
        self.takeSnapshopItem.setDisabled(True)
        self.view.setWindowTitle("Google maps oblique")

    def switch2SV(self):
        # Procedure to operate switch to carrers3d dialog set
        self.view.BE.hide()
        self.view.SV.show()
        #self.view.btnSwitchView.setIcon(QtGui.QIcon(os.path.join(self.dirPath, "res", "icoGMaps.png")))
        self.takeSnapshopItem.setDisabled(False)
        self.view.setWindowTitle("Carrers 3D")

    def openInBrowserBE(self):
        # open an external browser with the Carrers 3D url for location
        p = self.snapshotOutput.setCurrentPOV()
        webbrowser.open_new(f"https://visors.icgc.cat/catalunya-digital/carrers-3d/#/panorama?lat={p['lat']}&lon={p['lon']}")

    def openExternalUrl(self, url):
        core.QgsMessageLog.logMessage(url.toString(), tag="go2carrers3d", level=core.Qgis.Info)
        webbrowser.open_new(url.toString())

    def openInBrowserSV(self):
        # open an external browser with the Carrers 3D url for current location
        p = self.snapshotOutput.setCurrentPOV()
        webbrowser.open_new_tab(f"https://visors.icgc.cat/catalunya-digital/carrers-3d/#/panorama?lat={p['lat']}&lon={p['lon']}")

    def openInBrowserOnCTRLClick(self):
        webbrowser.open(f"https://visors.icgc.cat/catalunya-digital/carrers-3d/#/panorama?lat={self.pointWgs84.y()}&lon={self.pointWgs84.x()}", new=0, autoraise=True)

    def transformToWGS84(self, pPoint):
        # transformation from the current SRS to WGS84
        crcMappaCorrente = self.iface.mapCanvas().mapSettings().destinationCrs() # get current crs
        crsSrc = crcMappaCorrente
        crsDest = core.QgsCoordinateReferenceSystem("EPSG:4326")  # WGS84
        xform = core.QgsCoordinateTransform(crsSrc, crsDest, core.QgsProject.instance())
        return xform.transform(pPoint) # forward transformation: src -> dest

    def transformToCurrentSRS(self, pPoint):
        # transformation from the current SRS to WGS84
        crcMappaCorrente = self.iface.mapCanvas().mapSettings().destinationCrs() # get current crs
        crsDest = crcMappaCorrente
        crsSrc = core.QgsCoordinateReferenceSystem("EPSG:4326")  # WGS84
        xform = core.QgsCoordinateTransform(crsSrc, crsDest, core.QgsProject.instance())
        return xform.transform(pPoint) # forward transformation: src -> dest

    def canvasPressEvent(self, event):
        # Press event handler inherited from QgsMapTool used to store the given location in WGS84 long/lat
        self.pressed=True
        self.pressx = event.pos().x()
        self.pressy = event.pos().y()
        self.movex = event.pos().x()
        self.movey = event.pos().y()
        self.highlight=gui.QgsRubberBand(self.iface.mapCanvas(),core.QgsWkbTypes.LineGeometry )
        self.highlight.setColor(QtCore.Qt.yellow)
        self.highlight.setWidth(5)
        self.PressedPoint = self.canvas.getCoordinateTransform().toMapCoordinates(self.pressx, self.pressy)
        self.pointWgs84 = self.transformToWGS84(self.PressedPoint)

    def canvasMoveEvent(self, event):
        # Moved event handler inherited from QgsMapTool needed to highlight the direction that is giving by the user
        if self.pressed:
            x = event.pos().x()
            y = event.pos().y()
            movedPoint = self.canvas.getCoordinateTransform().toMapCoordinates(x, y)
            self.highlight.reset()
            self.highlight.addPoint(self.PressedPoint)
            self.highlight.addPoint(movedPoint)


    def canvasReleaseEvent(self, event):
        # Release event handler inherited from QgsMapTool needed to calculate heading
        event.modifiers()
        if (event.modifiers() & QtCore.Qt.ControlModifier):
            CTRLPressed = True
        else:
            CTRLPressed = None
        self.pressed=None
        self.highlight.reset()
        self.releasedx = event.pos().x()
        self.releasedy = event.pos().y()
        if (self.releasedx==self.pressx)&(self.releasedy==self.pressy):
            self.heading=0
            result=0
        else:
            result = math.atan2((self.releasedx - self.pressx),(self.releasedy - self.pressy))
            result = math.degrees(result)+self.canvas.rotation()
            if result > 0:
                self.heading =  180 - result
            else:
                self.heading = 360 - (180 + result)
        if CTRLPressed:
            self.openInBrowserOnCTRLClick()
        else:
            self.openSVDialog()

    def openSVDialog(self, show=True):
        # procedure for compiling carrers3d and gmaps url with the given location and heading
        self.heading = math.trunc(self.heading)
        if show:
            self.view.setWindowTitle("Carrers3d")
            self.apdockwidget.setWidget(self.view)
            self.view.show()
            self.apdockwidget.raise_()
            self.view.activateWindow()
            self.view.BE.hide()
            self.view.SV.hide()
        self.viewHeight=self.view.size().height()
        self.viewWidth=self.view.size().width()

        route = f"#/info/mapiastreets/{self.pointWgs84.y()},{self.pointWgs84.x()}/{self.heading}/"
        self.gswDialogUrl = f"https://visors.icgc.cat/catalunya-digital/carrers-3d/{route}"
        self.bbeUrl = self.gswDialogUrl

        gswTitle = "Carrers 3D"
        core.QgsMessageLog.logMessage(QtCore.QUrl(self.gswDialogUrl).toString(), tag="go2carrers3d", level=core.Qgis.Info)
        core.QgsMessageLog.logMessage(self.bbeUrl, tag="go2carrers3d", level=core.Qgis.Info)
        self.httpConnecting = True
        self.view.SV.setUrl(QtCore.QUrl(QtCore.QDir.fromNativeSeparators(self.gswDialogUrl)))
        self.view.BE.setUrl(QtCore.QUrl(QtCore.QDir.fromNativeSeparators(self.bbeUrl)))
        self.view.SV.show()

        self.syncTimer.start()

    def StreetviewRun(self):
        # called by click on toolbar icon
        if self.apdockwidget.isVisible():
            self.apdockwidget.hide()
        else:
            self.apdockwidget.show()
            self.explore()

    def explore(self):
        self.view.resized.connect(self.resizeStreetview)
        gsvMessage="Click on map and drag the cursor to the desired direction to display Carrers 3D"
        self.iface.mainWindow().statusBar().showMessage(gsvMessage)
        self.dumLayer.setCrs(self.iface.mapCanvas().mapSettings().destinationCrs())
        self.canvas.setMapTool(self)

    def disableControlShape(self):
        try:
            self.controlShape.reset()
        except:
            pass

    def noSVConnectionsPending(self,reply):
        print ("finished loading SV")
        self.httpConnecting = None
        if reply.error() == QtNetwork.QNetworkReply.NoError:
            pass
        elif reply.error() == QtNetwork.QNetworkReply.ContentNotFoundError:
            failedUrl = reply.request.url()
            httpStatus = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute).toInt()
            httpStatusMessage = reply.attribute(QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute).toByteArray()
            core.QgsMessageLog.logMessage("STREETVIEW FAILED REQUEST: {} {} {}".format(failedUrl,httpStatus,httpStatusMessage), tag="go2carrers3d", level=core.Qgis.Critical)
        else:
            core.QgsMessageLog.logMessage("STREETVIEW OTHER CONNECTION ERROR: {}".format(reply.error()), tag="go2carrers3d", level=core.Qgis.Critical)

    def noGMConnectionsPending(self, reply):
        if reply.error() == QtNetwork.QNetworkReply.NoError:
            pass
        elif reply.error() == QtNetwork.QNetworkReply.ContentNotFoundError:
            failedUrl = reply.request.url()
            httpStatus = reply.attribute(QtNetwork.QNetworkRequest.HttpStatusCodeAttribute).toInt()
            httpStatusMessage = reply.attribute(QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute).toByteArray()
            core.QgsMessageLog.logMessage("GM FAILED REQUEST: {} {} {}".format(failedUrl,httpStatus,httpStatusMessage), tag="go2carrers3d", level=core.Qgis.Critical)
        else:
            core.QgsMessageLog.logMessage("GM OTHER CONNECTION ERROR: {}".format(reply.error()), tag="go2carrers3d", level=core.Qgis.Critical)

    def loadFinishedAction(self,ok):
        if ok:
            core.QgsMessageLog.logMessage("Finished loading", tag="go2carrers3d", level=core.Qgis.Info)
            pass
        else:
            core.QgsMessageLog.logMessage("Failed loading", tag="go2carrers3d", level=core.Qgis.Critical)
            pass

    def setupInspector(self):
        print ("setupInspector")
        return
        self.page = self.view.SV.page()
        self.page.settings().setAttribute(QtWebKit.QWebSettings.DeveloperExtrasEnabled, True)
        self.webInspector = QtWebKitWidgets.QWebInspector(self)
        self.webInspector.setPage(self.page)
