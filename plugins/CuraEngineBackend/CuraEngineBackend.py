from UM.Backend.Backend import Backend
from UM.Application import Application
from UM.Scene.SceneNode import SceneNode
from UM.Scene.Iterator.DepthFirstIterator import DepthFirstIterator
from UM.Preferences import Preferences
from UM.Math.Vector import Vector

from . import Cura_pb2
from . import ProcessSlicedObjectListJob
from . import ProcessGCodeJob

import threading
import struct
import numpy

class CuraEngineBackend(Backend):
    def __init__(self):
        super().__init__()

        self._scene = Application.getInstance().getController().getScene()
        self._scene.sceneChanged.connect(self._onSceneChanged)

        self._settings = None
        Application.getInstance().activeMachineChanged.connect(self._onActiveMachineChanged)
        self._onActiveMachineChanged()

        self._changeTimer = None

        self._message_handlers[Cura_pb2.SlicedObjectList] = self._onSlicedObjectListMessage
        self._message_handlers[Cura_pb2.Progress] = self._onProgressMessage
        self._message_handlers[Cura_pb2.GCode] = self._onGCodeMessage
        self._message_handlers[Cura_pb2.ObjectPrintTime] = self._onObjectPrintTimeMessage

        self._center = None

    def getEngineCommand(self):
        return [Preferences.getPreference("BackendLocation"), '--connect', "127.0.0.1:{0}".format(self._port)]

    def _onSceneChanged(self, source):
        if (type(source) is not SceneNode) or (source is self._scene.getRoot()):
            return

        self._onChanged()

    def _onActiveMachineChanged(self):
        if self._settings:
            self._settings.settingChanged.disconnect(self._onSettingChanged)

        self._settings = Application.getInstance().getActiveMachine()
        if self._settings:
            self._settings.settingChanged.connect(self._onSettingChanged)
            self._onChanged()

    def _onSettingChanged(self, setting):
        self._onChanged()

    def _onSlicedObjectListMessage(self, message):
        job = ProcessSlicedObjectListJob.ProcessSlicedObjectListJob(message, self._center)
        job.start()

    def _onProgressMessage(self, message):
        self.processingProgress.emit(message.amount)

    def _onGCodeMessage(self, message):
        job = ProcessGCodeJob.ProcessGCodeJob(message)
        job.start()

    def _onObjectPrintTimeMessage(self, message):
        pass

    def _createSocket(self):
        super()._createSocket()
        
        self._socket.registerMessageType(1, Cura_pb2.ObjectList)
        self._socket.registerMessageType(2, Cura_pb2.SlicedObjectList)
        self._socket.registerMessageType(3, Cura_pb2.Progress)
        self._socket.registerMessageType(4, Cura_pb2.GCode)
        self._socket.registerMessageType(5, Cura_pb2.ObjectPrintTime)
        self._socket.registerMessageType(6, Cura_pb2.SettingList)

    def _onChanged(self):
        if not self._settings:
            return

        if self._changeTimer:
            return

        self._changeTimer = threading.Timer(1, self._onChangeTimerFinished)
        self._changeTimer.start()

    def _onChangeTimerFinished(self):
        objects = []
        for node in DepthFirstIterator(self._scene.getRoot()):
            if type(node) is SceneNode and node.getMeshData():
                objects.append(node)

        if not objects:
            self._changeTimer = None
            return #No point in slicing an empty build plate

        self._sendSettings()

        self._scene.acquireLock()

        msg = Cura_pb2.ObjectList()

        #TODO: All at once/one at a time mode
        center = Vector()
        for object in objects:
            center += object.getPosition()

            meshData = object.getMeshData()

            obj = msg.objects.add()
            obj.id = id(object)

            verts = numpy.array(meshData.getVertices(), copy=True)
            verts[:,[1,2]] = verts[:,[2,1]]
            obj.vertices = verts.tostring()

            #if meshData.hasNormals():
                #obj.normals = meshData.getNormalsAsByteArray()

            #if meshData.hasIndices():
                #obj.indices = meshData.getIndicesAsByteArray()

        self._scene.releaseLock()

        center /= float(len(objects))
        if not self._settings.getSettingValueByKey('machine_center_is_zero'):
            center.setX(center.x + self._settings.getSettingValueByKey('machine_width') / 2)
            center.setZ(center.z + self._settings.getSettingValueByKey('machine_depth') / 2)

        posmsg = Cura_pb2.SettingList()
        posX = posmsg.settings.add()
        posX.name = 'position.X'
        posX.value = str(int(center.x * 1000)).encode('utf-8')
        posY = posmsg.settings.add()
        posY.name = 'position.Y'
        posY.value = str(int(center.z * 1000)).encode('utf-8')
        posZ = posmsg.settings.add()
        posZ.name = 'position.Z'
        posZ.value = str(int(0)).encode('utf-8')
        self._socket.sendMessage(posmsg)

        self._center = center

        self._socket.sendMessage(msg)

        self._changeTimer = None

    def _sendSettings(self):
        extruder = 0

        settings = {
            'extruderNr': extruder,
            'layerThickness': int(self._settings.getSettingValueByKey('layer_height') * 1000),
            'initialLayerThickness': int(self._settings.getSettingValueByKey('layer_height_0') * 1000),
            'printTemperature': int(self._settings.getSettingValueByKey('material_print_temperature')),
            'bedTemperature': int(self._settings.getSettingValueByKey('material_bed_temperature') * 100),
            'filamentDiameter': int(self._settings.getSettingValueByKey('material_diameter') * 1000),
            'filamentFlow': int(self._settings.getSettingValueByKey('material_flow')),
            'layer0extrusionWidth': int(self._settings.getSettingValueByKey('wall_line_width_0') * 1000),
            'extrusionWidth': int(self._settings.getSettingValueByKey('wall_line_width_x') * 1000),
            'insetCount': int(self._settings.getSettingValueByKey('wall_line_count')),
            'downSkinCount': int(self._settings.getSettingValueByKey('bottom_layers')),
            'upSkinCount': int(self._settings.getSettingValueByKey('top_layers')),
            'skirtDistance': int(self._settings.getSettingValueByKey('skirt_gap') * 1000),
            'skirtLineCount': int(self._settings.getSettingValueByKey('skirt_line_count')),
            'skirtMinLength': int(self._settings.getSettingValueByKey('skirt_minimal_length') * 1000),

            'retractionAmount': int(self._settings.getSettingValueByKey('retraction_amount') * 1000),
            'retractionAmountPrime': int(0 * 1000),
            # 'retractionAmountExtruderSwitch': int(fbk('') * 1000),
            'retractionSpeed': int(self._settings.getSettingValueByKey('retraction_speed')),
            'retractionPrimeSpeed': int(self._settings.getSettingValueByKey('retraction_speed')),
            'retractionMinimalDistance': int(self._settings.getSettingValueByKey('retraction_min_travel') * 1000),
            'minimalExtrusionBeforeRetraction': int(self._settings.getSettingValueByKey('retraction_minimal_extrusion') * 1000),
            'retractionZHop': int(self._settings.getSettingValueByKey('retraction_hop') * 1000),

            'enableCombing': 1 if self._settings.getSettingValueByKey('retraction_combing') else 0,
            # 'enableOozeShield': int(fbk('') * 1000),
            # 'wipeTowerSize': int(fbk('') * 1000),
            # 'multiVolumeOverlap': int(fbk('') * 1000),

            'initialSpeedupLayers': int(self._settings.getSettingValueByKey('speed_slowdown_layers')),
            'initialLayerSpeed': int(self._settings.getSettingValueByKey('speed_layer_0')),
            'skirtSpeed': int(self._settings.getSettingValueByKey('skirt_speed')),
            'inset0Speed': int(self._settings.getSettingValueByKey('speed_wall_0')),
            'insetXSpeed': int(self._settings.getSettingValueByKey('speed_wall_x')),
            'supportSpeed': int(self._settings.getSettingValueByKey('speed_support')),
            'moveSpeed': int(self._settings.getSettingValueByKey('speed_travel')),
            #'fanFullOnLayerNr': int(fbk('cool_fan_full_layer')),

            'infillOverlap': int(self._settings.getSettingValueByKey('fill_overlap')),
            'infillSpeed': int(self._settings.getSettingValueByKey('speed_infill')),

            'minimalLayerTime': int(self._settings.getSettingValueByKey('cool_min_layer_time')),
            'minimalFeedrate': int(self._settings.getSettingValueByKey('cool_min_speed')),
            'coolHeadLift': 1 if self._settings.getSettingValueByKey('cool_lift_head') else 0,
            'fanSpeedMin': self._settings.getSettingValueByKey('cool_fan_speed_min'),
            'fanSpeedMax': self._settings.getSettingValueByKey('cool_fan_speed_max'),

            'spiralizeMode': 1 if self._settings.getSettingValueByKey('magic_spiralize') == 'True' else 0,

        }

        if self._settings.getSettingValueByKey('top_bottom_pattern') == 'Lines':
            settings['skinPattern'] = 'SKIN_LINES'
        elif self._settings.getSettingValueByKey('top_bottom_pattern') == 'Concentric':
            settings['skinPattern'] = 'SKIN_CONCENTRIC'

        if self._settings.getSettingValueByKey('fill_pattern') == 'Grid':
            settings['infillPattern'] = 'INFILL_GRID'
        elif self._settings.getSettingValueByKey('fill_pattern') == 'Lines':
            settings['infillPattern'] = 'INFILL_LINES'
        elif self._settings.getSettingValueByKey('fill_pattern') == 'Concentric':
            settings['infillPattern'] = 'INFILL_CONCENTRIC'
        elif self._settings.getSettingValueByKey('fill_pattern') == 'ZigZag':
            settings['infillPattern'] = 'INFILL_ZIGZAG'

        adhesion_type = self._settings.getSettingValueByKey('adhesion_type')
        if adhesion_type == 'Raft':
            settings['raftMargin'] = int(self._settings.getSettingValueByKey('raft_margin') * 1000)
            settings['raftLineSpacing'] = int(self._settings.getSettingValueByKey('raft_line_spacing') * 1000)
            settings['raftBaseThickness'] = int(self._settings.getSettingValueByKey('raft_base_thickness') * 1000)
            settings['raftBaseLinewidth'] = int(self._settings.getSettingValueByKey('raft_base_linewidth') * 1000)
            settings['raftBaseSpeed'] = int(self._settings.getSettingValueByKey('raft_base_speed') * 1000)
            settings['raftInterfaceThickness'] = int(self._settings.getSettingValueByKey('raft_interface_thickness') * 1000)
            settings['raftInterfaceLinewidth'] = int(self._settings.getSettingValueByKey('raft_interface_linewidth') * 1000)
            settings['raftInterfaceLineSpacing'] = int(self._settings.getSettingValueByKey('raft_line_spacing') * 1000)
            settings['raftFanSpeed'] = 0
            settings['raftSurfaceThickness'] = int(self._settings.getSettingValueByKey('layer_height_0') * 1000)
            settings['raftSurfaceLinewidth'] = int(self._settings.getSettingValueByKey('wall_line_width_x') * 1000)
            settings['raftSurfaceLineSpacing'] = int(self._settings.getSettingValueByKey('wall_line_width_x') * 1000)
            settings['raftSurfaceLayers'] = int(self._settings.getSettingValueByKey('raft_surface_layers'))
            settings['raftSurfaceSpeed'] = int(self._settings.getSettingValueByKey('speed_layer_0') * 1000)
            settings['raftAirGap'] = int(self._settings.getSettingValueByKey('raft_airgap') * 1000)
            settings['skirtLineCount'] = 0
            pass
        elif adhesion_type == 'Brim':
            settings['skirtDistance'] = 0
            settings['skirtLineCount'] = self._settings.getSettingValueByKey('brim_line_count')

        if self._settings.getSettingValueByKey('support_type') == 'None':
            settings['supportType'] = ''
            settings['supportAngle'] = -1
        else:
            settings['supportType'] = 'LINES'
            settings['supportAngle'] = self._settings.getSettingValueByKey('support_angle')
            settings['supportOnBuildplateOnly'] = 1 if self._settings.getSettingValueByKey('support_type') == 'Touching Buildplate' else 0
            settings['supportLineDistance'] = int(100 * self._settings.getSettingValueByKey('wall_line_width_x') * 1000 / self._settings.getSettingValueByKey('support_fill_rate'))
            settings['supportXYDistance'] = int(self._settings.getSettingValueByKey('support_xy_distance') * 1000)
            settings['supportZDistance'] = int(self._settings.getSettingValueByKey('support_z_distance') * 1000)
            settings['supportZDistanceBottom'] = int(self._settings.getSettingValueByKey('support_top_distance') * 1000)
            settings['supportZDistanceTop'] = int(self._settings.getSettingValueByKey('support_bottom_distance') * 1000)
            settings['supportJoinDistance'] = int(self._settings.getSettingValueByKey('support_join_distance') * 1000)
            settings['supportAreaSmoothing'] = int(self._settings.getSettingValueByKey('support_area_smoothing') * 1000)
            settings['supportMinimalAreaSqrt'] = int(self._settings.getSettingValueByKey('support_minimal_diameter') * 1000) if self._settings.getSettingValueByKey('support_use_towers') else 0
            settings['supportTowerDiameter'] = int(self._settings.getSettingValueByKey('support_tower_diameter') * 1000)
            settings['supportTowerRoofAngle'] = int(self._settings.getSettingValueByKey('support_tower_roof_angle'))
            settings['supportConnectZigZags'] = 1 if self._settings.getSettingValueByKey('support_connect_zigzags') else 0 
            settings['supportExtruder'] = -1
            if self._settings.getSettingValueByKey('support_pattern') == 'Grid':
                settings['supportType'] = 'GRID'
            elif self._settings.getSettingValueByKey('support_pattern') == 'Lines':
                settings['supportType'] = 'LINES'
            elif self._settings.getSettingValueByKey('support_pattern') == 'ZigZag':
                settings['supportType'] = 'ZIGZAG'

        settings['sparseInfillLineDistance'] = -1
        if self._settings.getSettingValueByKey('fill_sparse_density') >= 100:
            settings['sparseInfillLineDistance'] = self._settings.getSettingValueByKey('wall_line_width_x')
            settings['downSkinCount'] = 10000
            settings['upSkinCount'] = 10000
        elif self._settings.getSettingValueByKey('fill_sparse_density') > 0:
            settings['sparseInfillLineDistance'] = int(100 * self._settings.getSettingValueByKey('wall_line_width_x') * 1000 / self._settings.getSettingValueByKey('fill_sparse_density'))
        settings['sparseInfillCombineCount'] = int(round(self._settings.getSettingValueByKey('fill_sparse_combine')))

        gcodeFlavor = self._settings.getSettingValueByKey('machine_gcode_flavor')
        if gcodeFlavor == 'UltiGCode':
            settings['gcodeFlavor'] = 1
        elif gcodeFlavor == 'Makerbot':
            settings['gcodeFlavor'] = 2
        elif gcodeFlavor == 'BFB':
            settings['gcodeFlavor'] = 3
        elif gcodeFlavor == 'Mach3':
            settings['gcodeFlavor'] = 4
        elif gcodeFlavor == 'Volumetric':
            settings['gcodeFlavor'] = 5
        else:
            settings['gcodeFlavor'] = 0

        settings['startCode'] = self._settings.getSettingValueByKey('machine_start_gcode')
        settings['endCode'] = self._settings.getSettingValueByKey('machine_end_gcode')

        #for n in range(1, self._machine.getMaxNozzles()):
        n = 1
        settings['extruderOffset1.X'] = int(self._settings.getSettingValueByKey('machine_nozzle_offset_x_1') * 1000)
        settings['extruderOffset1.Y'] = int(self._settings.getSettingValueByKey('machine_nozzle_offset_y_1') * 1000)

        msg = Cura_pb2.SettingList()
        for key, value in settings.items():
            s = msg.settings.add()
            s.name = key
            s.value = str(value).encode('utf-8')

        self._socket.sendMessage(msg)
