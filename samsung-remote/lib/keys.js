'use strict';

// The key codes a Tizen TV accepts over the remote-control channel.
// Grouped the way the on-screen remote lays them out; the server uses the
// flattened set to reject anything that isn't a real key.

const GROUPS = {
  power: [
    { key: 'KEY_POWER', label: 'Power' },
    { key: 'KEY_POWEROFF', label: 'Power off' },
  ],
  navigation: [
    { key: 'KEY_UP', label: 'Up' },
    { key: 'KEY_DOWN', label: 'Down' },
    { key: 'KEY_LEFT', label: 'Left' },
    { key: 'KEY_RIGHT', label: 'Right' },
    { key: 'KEY_ENTER', label: 'Select' },
    { key: 'KEY_RETURN', label: 'Back' },
    { key: 'KEY_EXIT', label: 'Exit' },
    { key: 'KEY_HOME', label: 'Home' },
    { key: 'KEY_MENU', label: 'Menu' },
    { key: 'KEY_TOOLS', label: 'Tools' },
    { key: 'KEY_INFO', label: 'Info' },
    { key: 'KEY_GUIDE', label: 'Guide' },
  ],
  volume: [
    { key: 'KEY_VOLUP', label: 'Volume up' },
    { key: 'KEY_VOLDOWN', label: 'Volume down' },
    { key: 'KEY_MUTE', label: 'Mute' },
  ],
  channel: [
    { key: 'KEY_CHUP', label: 'Channel up' },
    { key: 'KEY_CHDOWN', label: 'Channel down' },
    { key: 'KEY_CH_LIST', label: 'Channel list' },
    { key: 'KEY_PRECH', label: 'Previous channel' },
  ],
  numbers: [
    { key: 'KEY_0', label: '0' },
    { key: 'KEY_1', label: '1' },
    { key: 'KEY_2', label: '2' },
    { key: 'KEY_3', label: '3' },
    { key: 'KEY_4', label: '4' },
    { key: 'KEY_5', label: '5' },
    { key: 'KEY_6', label: '6' },
    { key: 'KEY_7', label: '7' },
    { key: 'KEY_8', label: '8' },
    { key: 'KEY_9', label: '9' },
  ],
  playback: [
    { key: 'KEY_PLAY', label: 'Play' },
    { key: 'KEY_PAUSE', label: 'Pause' },
    { key: 'KEY_STOP', label: 'Stop' },
    { key: 'KEY_REWIND', label: 'Rewind' },
    { key: 'KEY_FF', label: 'Fast forward' },
    { key: 'KEY_REC', label: 'Record' },
  ],
  source: [
    { key: 'KEY_SOURCE', label: 'Source' },
    { key: 'KEY_HDMI', label: 'HDMI' },
    { key: 'KEY_TV', label: 'TV' },
  ],
  colour: [
    { key: 'KEY_RED', label: 'Red' },
    { key: 'KEY_GREEN', label: 'Green' },
    { key: 'KEY_YELLOW', label: 'Yellow' },
    { key: 'KEY_CYAN', label: 'Blue' },
  ],
  extras: [
    { key: 'KEY_CONTENTS', label: 'Smart Hub' },
    { key: 'KEY_SUB_TITLE', label: 'Subtitles' },
    { key: 'KEY_PICTURE_SIZE', label: 'Picture size' },
    { key: 'KEY_SLEEP', label: 'Sleep timer' },
    { key: 'KEY_AD', label: 'Audio description' },
    { key: 'KEY_MTS', label: 'Sound mode' },
  ],
};

const ALL_KEYS = new Set(Object.values(GROUPS).flat().map((entry) => entry.key));

// App IDs are stable across Tizen models; these are the ones worth a shortcut.
const APPS = [
  { id: '3201907018807', name: 'Netflix' },
  { id: '111299001912', name: 'YouTube' },
  { id: '3201910019365', name: 'Prime Video' },
  { id: '3201601007250', name: 'Spotify' },
  { id: '3201606009684', name: 'JioCinema' },
  { id: '3201512006785', name: 'Hotstar' },
];

function isKnownKey(key) {
  return ALL_KEYS.has(key);
}

module.exports = { GROUPS, ALL_KEYS, APPS, isKnownKey };
