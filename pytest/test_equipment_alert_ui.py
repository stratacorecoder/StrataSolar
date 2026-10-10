'''Actual SPA rendering/localization also runs without a browser process.'''

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from alert_catalog import ALERT_COMPONENTS

ROOT = Path(__file__).resolve().parents[1]
NEW_RULES = ('inverter_dc_without_ac', 'panels_mppt_imbalance', 'battery_fault',
             'battery_soc_jump', 'battery_charge_stalled')

PROBE = r'''
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
class Element {
    constructor() {
        this.children = [];
        this.dataset = {};
        this.style = {};
        this.classList = {add() {}};
        this.textContent = '';
    }
    appendChild(child) { this.children.push(child); }
    set innerHTML(value) { this.children = []; }
}
const list = new Element();
const context = vm.createContext({
    document: {
        activeElement: null,
        getElementById(id) { return id === 'alerts_list' ? list : null; },
        createElement() { return new Element(); },
    },
    setElementVisible() {},
});
vm.runInContext(fs.readFileSync('site/js/localization.js', 'utf8'), context);
vm.runInContext(fs.readFileSync('site/js/forecast_alerts.js', 'utf8'), context);
vm.runInContext('gCurLang = ' + input.lang, context);
context.alerts = input.alerts;
vm.runInContext('renderAlertsListDom(alerts, [], false)', context);
const rendered = list.children.map(li => ({
    title: li.children[0].children[0].textContent,
    message: li.children[1].textContent,
    meta: li.children[2].textContent,
    component: li.children[2].dataset.alertComponent,
}));
const components = vm.runInContext(
    "['battery','panels','inverter','system','constructor'].map(localizedAlertComponent)", context);
const english = vm.runInContext(
    'alerts.map(a => ALERT_RULE_STRINGS[a.rule_id][0])', context);
const translations = vm.runInContext(
    "alerts.map(a => getTranslationString('alerts_msg_' + a.rule_id))", context);
// Same ids/statuses with a changed component must refresh the label.
context.alerts[0].component = 'system';
vm.runInContext('renderAlertsListDom(alerts, [], false)', context);
const changedComponent = list.children[0].children[2].dataset.alertComponent;
process.stdout.write(JSON.stringify({rendered, components, english, translations, changedComponent}));
'''


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
@pytest.mark.parametrize('lang,components', [
    (1, ['Battery', 'PV panels', 'Inverter', 'System', 'System']),
    (2, ['Batterie', 'PV-Module', 'Wechselrichter', 'System', 'System']),
    (3, ['Batterie', 'Panneaux PV', 'Onduleur', 'Système', 'Système']),
])
def test_equipment_components_and_new_messages_render_in_all_languages(lang, components):
    alerts = [{'id': i, 'rule_id': rule, 'component': ALERT_COMPONENTS[rule],
               'title': 'Stored English', 'message': 'Stored English',
               'status': 'open', 'acknowledged_at': 'ack'}
              for i, rule in enumerate(NEW_RULES, 1)]
    result = subprocess.run(['node', '-e', PROBE], input=json.dumps({'lang': lang, 'alerts': alerts}),
                            text=True, capture_output=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['components'] == components
    assert data['changedComponent'] == 'system'
    for alert, row, message, english in zip(alerts, data['rendered'], data['translations'], data['english']):
        assert row['component'] == alert['component']
        assert row['meta'].startswith(components[['battery', 'panels', 'inverter', 'system'].index(alert['component'])])
        assert row['message'] == message
        assert message != 'alerts_msg_' + alert['rule_id']
        assert row['title'] != 'Stored English'
        if lang != 1:
            assert row['title'] != english
