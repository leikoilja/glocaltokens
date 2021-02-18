# Right now this is pretty useless, a great confusion. Don't delete just in case it's useful in the future.

# See https://developers.google.com/assistant/smarthome/traits
AppSelector = "action.devices.traits.AppSelector"
ArmDisarm = "action.devices.traits.ArmDisarm"
Brightness = "action.devices.traits.Brightness"
CameraStream = "action.devices.traits.CameraStream"
Channel = "action.devices.traits.Channel"
ColorSetting = "action.devices.traits.ColorSetting"
ColorTemperature = "action.devices.traits.ColorTemperature"
Cook = "action.devices.traits.Cook"
Dispense = "action.devices.traits.Dispense"
Dock = "action.devices.traits.Dock"
EnergyStorage = "action.devices.traits.EnergyStorage"
FanSpeed = "action.devices.traits.FanSpeed"
Fill = "action.devices.traits.Fill"
HumiditySetting = "action.devices.traits.HumiditySetting"
InputSelector = "action.devices.traits.InputSelector"
LightEffects = "action.devices.traits.LightEffects"
Locator = "action.devices.traits.Locator"
LockUnlock = "action.devices.traits.LockUnlock"
MediaState = "action.devices.traits.MediaState"
Modes = "action.devices.traits.Modes"
NetworkControl = "action.devices.traits.NetworkControl"
OnOff = "action.devices.traits.OnOff"
OpenClose = "action.devices.traits.OpenClose"
Reboot = "action.devices.traits.Reboot"
Rotation = "action.devices.traits.Rotation"
RunCycle = "action.devices.traits.RunCycle"
SensorState = "action.devices.traits.SensorState"
Scene = "action.devices.traits.Scene"
SoftwareUpdate = "action.devices.traits.SoftwareUpdate"
StartStop = "action.devices.traits.StartStop"
StatusReport = "action.devices.traits.StatusReport"
TemperatureControl = "action.devices.traits.TemperatureControl"
TemperatureSetting = "action.devices.traits.TemperatureSetting"
Timer = "action.devices.traits.Timer"
Toggles = "action.devices.traits.Toggles"
TransportControl = "action.devices.traits.TransportControl"
Volume = "action.devices.traits.Volume"

# See https://developers.google.com/assistant/smarthome/guides
SMART_HOME_DEVICE_TYPES = {
    "AC_UNIT": {FanSpeed, TemperatureSetting},
    "AIRCOOLER": {FanSpeed, HumiditySetting, TemperatureSetting},
    "AIRFRESHENER": {Modes, Toggles, OnOff},
    "AIRPURIFIER": {FanSpeed, SensorState, OnOff},
    "AUDIO_VIDEO_RECEIVER": {
        AppSelector,
        MediaState,
        TransportControl,
        InputSelector,
        OnOff,
        Volume,
    },
    "AWNING": {OpenClose},
    "BATHTUB": {Fill, TemperatureControl, StartStop},
    "BED": {Scene, Modes},
    "BLENDER": {Cook, StartStop, Timer, OnOff},
    "BLINDS": {Rotation, OpenClose},
    "BOILER": {TemperatureControl, OnOff},
    "CAMERA": {CameraStream},
    "CARBON_MONOXIDE_DETECTOR": {SensorState},
    "CHARGER": {EnergyStorage},
    "CLOSET": {OpenClose},
    "COFFEE_MAKER": {Cook, TemperatureControl, OnOff},
    "COOKTOP": {Cook, Timer, OnOff},
    "CURTAIN": {OpenClose},
    "DEHUMIDIFIER": {FanSpeed, HumiditySetting, StartStop, OnOff},
    "DEHYDRATOR": {Cook, StartStop, Timer, OnOff},
    "DISHWASHER": {OnOff, RunCycle, StartStop},
    "DOOR": {LockUnlock, OpenClose},
    "DRAWER": {OpenClose},
    "DRYER": {Modes, OnOff, RunCycle, Toggles, StartStop},
    "FAN": {FanSpeed, OnOff},
    "FAUCET": {Dispense, StartStop, TemperatureControl},
    "FIREPLACE": {Modes, Toggles, OnOff},
    "FREEZER": {TemperatureControl},
    "FRYER": {Cook, StartStop, Timer, OnOff},
    "GARAGE": {OpenClose},
    "GATE": {LockUnlock, OpenClose},
    "GRILL": {Cook, OnOff, Timer, StartStop},
    "HEATER": {FanSpeed, TemperatureSetting},
    "HOOD": {Brightness, FanSpeed, OnOff},
    "HUMIDIFIER": {FanSpeed, HumiditySetting, StartStop, OnOff},
    "KETTLE": {TemperatureControl, OnOff},
    "LIGHT": {ColorSetting, Brightness, OnOff},
    "LOCK": {LockUnlock},
    "MICROWAVE": {Cook, Timer, StartStop},
    "MOP": {Dock, EnergyStorage, Locator, OnOff, RunCycle, StartStop},
    "MOWER": {Dock, EnergyStorage, Locator, OnOff, RunCycle, StartStop},
    "MULTICOOKER": {Cook, StartStop, Timer, OnOff},
    "NETWORK": {Reboot, SoftwareUpdate, NetworkControl},
    "OUTLET": {OnOff},
    "OVEN": {Cook, TemperatureControl, Timer, OnOff},
    "PERGOLA": {Rotation, OpenClose},
    "PETFEEDER": {OnOff, StartStop, Dispense},
    "PRESSURECOOKER": {Cook, Timer, OnOff},
    "RADIATOR": {Modes, Toggles, OnOff},
    "REFRIGERATOR": {TemperatureControl},
    "REMOTECONTROL": {
        AppSelector,
        Channel,
        InputSelector,
        MediaState,
        OnOff,
        TransportControl,
        Volume,
    },
    "ROUTER": {Reboot, SoftwareUpdate, NetworkControl},
    "SCENE": {Scene},
    "SECURITYSYSTEM": {StatusReport, ArmDisarm},
    "SENSOR": {EnergyStorage, SensorState},
    "SETTOP": {Volume, OnOff, AppSelector, MediaState, Channel, TransportControl},
    "SHOWER": {StartStop, TemperatureControl},
    "SHUTTER": {Rotation, OpenClose},
    "SMOKE_DETECTOR": {SensorState},
    "SOUNDBAR": {
        AppSelector,
        InputSelector,
        MediaState,
        OnOff,
        TransportControl,
        Volume,
    },
    "SOUSVIDE": {Cook, StartStop, Timer, OnOff},
    "SPEAKER": {
        AppSelector,
        InputSelector,
        MediaState,
        OnOff,
        TransportControl,
        Volume,
    },
    "SPRINKLER": {Timer, StartStop},
    "STANDMIXER": {Cook, StartStop, OnOff},
    "STREAMING_BOX": {
        InputSelector,
        OnOff,
        AppSelector,
        MediaState,
        TransportControl,
        Volume,
    },
    "STREAMING_SOUNDBAR": {
        InputSelector,
        OnOff,
        AppSelector,
        MediaState,
        TransportControl,
        Volume,
    },
    "STREAMING_STICK": {OnOff, AppSelector, MediaState, TransportControl, Volume},
    "SWITCH": {Brightness, OnOff},
    "THERMOSTAT": {TemperatureSetting},
    "TV": {
        Channel,
        InputSelector,
        AppSelector,
        MediaState,
        OnOff,
        TransportControl,
        Volume,
    },
    "VACUUM": {Dock, EnergyStorage, Locator, OnOff, RunCycle, StartStop},
    "VALVE": {OpenClose},
    "WASHER": {Modes, OnOff, RunCycle, Toggles, StartStop},
    "WATERHEATER": {TemperatureControl, OnOff},
    "WATERPURIFIER": {OnOff, SensorState},
    "WATERSOFTENER": {OnOff, SensorState},
    "WINDOW": {LockUnlock, OpenClose},
    "YOGURTMAKER": {Cook, StartStop, Timer, OnOff},
}
