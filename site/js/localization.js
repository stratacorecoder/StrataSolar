
let gLangEn = 1;
let gLangDe = 2;
let gLangFr = 3;

let gCurLang = gLangEn;

let translations = [
    // HTML element ID  English (1)  German (2) French (3)

    // Navigation bar
    ["navbar_dropdown_language", "Language", "Sprache", "Langue"],

    // Side bar
    ["sidebar_headline_overview", "Overview", "Übersicht", "Aperçu"],
    ["sidebar_today", "Today", "Heute", "Aujourd'hui"],
    ["sidebar_statistics", "Statistics", "Statistiken", "Statistiques"],
    ["sidebar_dashboard", "Dashboard", "Dashboard", "Tableau de bord"],
    ["sidebar_headline_history", "History", "Historie", "Historique"],
    ["sidebar_by_day", "By Day", "Nach Tag", "Journalier"],
    ["sidebar_by_month", "By Month", "Nach Monat", "Mensuel"],
    ["sidebar_by_year", "By Year", "Nach Jahr", "Annuel"],
    ["sidebar_all_time", "All Time", "Gesamt", "Global"],
    ["sidebar_headline_misc", "Misc", "Sonstiges", "Outils"],
    ["sidebar_csv", "CSV Download", "CSV-Download", "Export CSV"],
    ["sidebar_alerts", "Alerts", "Meldungen", "Alertes"],

    // Forecast (dashboard)
    ["dash_card_forecast", "Forecast", "Prognose", "Prévision"],
    ["dash_forecast_status_label", "Status", "Status", "Statut"],
    ["dash_forecast_today_label", "Forecast today", "Prognose heute", "Prévision du jour"],
    ["dash_forecast_actual_label", "Actual so far", "Ist bisher", "Réel à ce jour"],
    ["dash_forecast_week_head_date", "Date", "Datum", "Date"],
    ["dash_forecast_week_head_prod", "Production", "Erzeugung", "Production"],
    ["dash_forecast_week_head_prod_short", "Prod.", "Erz.", "Prod."],
    ["dash_forecast_week_head_cons", "Consumption", "Verbrauch", "Consommation"],
    ["dash_forecast_week_head_cons_short", "Cons.", "Verb.", "Cons."],
    ["forecast_unavailable", "Forecast unavailable.", "Prognose nicht verfügbar.", "Prévision indisponible."],
    ["forecast_pending", "Forecast is being prepared.", "Prognose wird vorbereitet.", "Prévision en cours de préparation."],
    ["forecast_stale", "Forecast data is outdated; refresh pending.", "Prognosedaten veraltet; Aktualisierung ausstehend.", "Données de prévision obsolètes ; actualisation en attente."],
    ["forecast_chart_summary", "Cumulative forecast peak about %s kWh.", "Prognose-Maximum etwa %s kWh.", "Pic cumulé de prévision environ %s kWh."],
    ["forecast_disabled", "Forecasting is disabled.", "Prognose ist deaktiviert.", "Prévision désactivée."],
    ["forecast_insufficient_history", "Not enough history for a forecast yet.", "Noch zu wenig Historie für eine Prognose.", "Pas encore assez d'historique pour une prévision."],
    ["forecast_source_open_meteo", "Weather model (Open-Meteo), calibrated to your site.", "Wettermodell (Open-Meteo), an Ihre Anlage angepasst.", "Modèle météo (Open-Meteo), calibré sur votre site."],
    ["forecast_source_history", "Based on your recorded history.", "Basierend auf Ihrer Historie.", "Basé sur votre historique."],
    ["forecast_cumulative_forecast", "Forecast (cumulative)", "Prognose (kumuliert)", "Prévision (cumulée)"],
    ["dash_forecast_chart_aria_label", "Forecast intraday chart", "Tagesprognose-Diagramm", "Graphique de prévision intrajournalière"],

    // Alerts view
    ["headline_alerts", "Alerts", "Meldungen", "Alertes"],
    ["alerts_subtitle", "Operational issues detected by StrataSolar.", "Vom System erkannte Betriebsprobleme.", "Problèmes opérationnels détectés."],
    ["alerts_empty", "No open alerts.", "Keine offenen Meldungen.", "Aucune alerte ouverte."],
    ["alerts_acknowledge", "Acknowledge", "Bestätigen", "Accuser réception"],
    ["alerts_acknowledged", "acknowledged", "bestätigt", "accusé"],
    ["alerts_ack_failed", "Could not acknowledge alert.", "Meldung konnte nicht bestätigt werden.", "Impossible d'accuser réception de l'alerte."],
    ["alerts_open_count_summary", "%s open alerts", "%s offene Meldungen", "%s alertes ouvertes"],
    ["alerts_live_summary", "%s open alerts", "%s offene Meldungen", "%s alertes ouvertes"],
    ["sidebar_alerts_badge_label", "open alerts", "offene Meldungen", "alertes ouvertes"],
    ["sidebar_alerts_badge_with_count", "%s open alerts", "%s offene Meldungen", "%s alertes ouvertes"],
    ["alerts_load_more_btn", "Load older resolved alerts", "Ältere behobene Meldungen laden", "Charger les alertes résolues plus anciennes"],
    ["alerts_msg_device_unreachable", "The inverter has not responded within the expected interval.", "Der Wechselrichter hat nicht innerhalb des erwarteten Intervalls geantwortet.", "L'onduleur n'a pas répondu dans l'intervalle attendu."],
    ["alerts_msg_grabber_stale", "Energy recording has stopped updating.", "Die Energieaufzeichnung wird nicht mehr aktualisiert.", "L'enregistrement de l'énergie ne se met plus à jour."],
    ["alerts_msg_battery_low", "Battery state of charge is %s percent.", "Batterieladung beträgt %s Prozent.", "L'état de charge de la batterie est de %s pour cent."],
    ["alerts_msg_generic", "An operational issue was detected. See details in the dashboard or logs.", "Ein Betriebsproblem wurde erkannt. Details im Dashboard oder in den Logs.", "Un problème opérationnel a été détecté. Voir le tableau de bord ou les journaux."],
    ["alerts_msg_zero_production_daylight", "PV output is near zero during expected daylight hours.", "PV-Erzeugung ist während der erwarteten Tageslichtstunden nahe null.", "La production PV est proche de zéro pendant les heures de jour attendues."],
    ["alerts_msg_production_below_forecast", "Today's production is significantly below the forecast.", "Die heutige Erzeugung liegt deutlich unter der Prognose.", "La production du jour est nettement inférieure à la prévision."],
    ["alerts_msg_production_below_baseline", "Today's production is far below the recent median.", "Die heutige Erzeugung liegt weit unter dem jüngsten Median.", "La production du jour est bien en dessous de la médiane récente."],
    ["alerts_msg_production_spike", "Today's production is unusually high compared to recent days.", "Die heutige Erzeugung ist ungewöhnlich hoch im Vergleich zu den letzten Tagen.", "La production du jour est inhabituellement élevée par rapport aux jours récents."],
    ["alerts_msg_consumption_spike", "Today's consumption is unusually high compared to recent days.", "Der heutige Verbrauch ist ungewöhnlich hoch im Vergleich zu den letzten Tagen.", "La consommation du jour est inhabituellement élevée par rapport aux jours récents."],
    ["alerts_msg_counter_reset", "An energy counter dropped sharply (inverter reset or replacement).", "Ein Energiezähler ist stark gefallen (Reset oder Austausch des Wechselrichters).", "Un compteur d'énergie a chuté fortement (réinitialisation ou remplacement de l'onduleur)."],
    ["alerts_msg_negative_delta", "Energy counters decreased between polls.", "Energiezähler sind zwischen den Abfragen gesunken.", "Les compteurs d'énergie ont diminué entre les relevés."],
    ["alerts_msg_battery_stuck", "Battery state of charge has not changed during daylight.", "Der Batterieladestand hat sich bei Tageslicht nicht verändert.", "Le niveau de charge de la batterie n'a pas changé pendant le jour."],

    // Statistics
    ["headline_statistics", "Statistics", "Statistiken", "Statistiques"],
    ["stats_card_highest_prod", "Highest Production", "Höchste Erzeugung", "Production maximale"],
    ["stats_card_best_day", "Best Day", "Bester Tag", "Meilleure journée"],
    ["stats_card_best_month", "Best Month", "Bester Monat", "Meilleur mois"],
    ["stats_card_best_year", "Best Year", "Bestes Jahr", "Meilleure année"],
    ["stats_best_year_in", "in %s", "im Jahr %s", "en %s"],
    ["stats_card_averages", "Averages ", "Durchschnittswerte", "Moyennes"],
    ["stats_card_runtime", "Runtime ", "Laufzeit", "Temps de fonctionnement"],
    ["statistics_text_avg_daily_prod", "Average daily production ", "Durchschn. täglich erzeugt", "Production journalière moyenne"],
    ["statistics_text_start_date", "Date of commissioning ", "Inbetriebnahme der Anlage", "Date d'initialisation"],
    ["statistics_text_runtime", "Total runtime ", "Laufzeit der Anlage", "Durée totale"],

    // Dashboard
    ["headline_dashboard", "Dashboard", "Dashboard", "Tableau de bord"],
    ["dashboard_subtitle", "Last updated: ", "Letzte Aktualisierung: ", "Dernière actualisation : "],
    ["dash_info_no_data", "No data yet.", "Noch keine Daten.", "Pas encore de données."],
    ["dash_info_no_data_chart", "No data yet.", "Noch keine Daten.", "Pas encore de données."],

    ["dash_card_current", "Current", "Momentanwerte", "Maintenant"],
    ["dash_card_today", "Today", "Heutige Werte", "Aujourd'hui"],
    ["dash_card_all_time", "All Time", "Allzeit-Werte", "Total"],
    ["dash_card_24h", "Short Term History", "Aktueller Verlauf", "Dernières heures"],

    ["dash_text_today_produced", "Produced today", "Heute erzeugt", "Production du jour"],
    ["dash_text_today_consumed", "Consumed today", "Heute verbraucht", "Consommation du jour"],
    ["dash_text_today_fed_in", "Feed-in today", "Heute eingespeist", "Injection du jour"],
    ["dash_text_today_autarky", "Today's autarky", "Heutige Autarkie", "Autonomie du jour"],
    ["dash_text_today_earned", "Earned today", "Heute verdient", "Gain du jour"],

    ["dash_text_all_time_produced", "Produced in total", "Insgesamt erzeugt", "Production totale"],
    ["dash_text_all_time_consumed", "Consumed in total", "Insgesamt verbraucht", "Consommation totale"],
    ["dash_text_all_time_fed_in", "Feed-in total", "Insgesamt eingespeist", "Injection totale"],
    ["dash_text_all_time_autarky", "Average autarky", "Durchschn. Autarkie", "Autonomie moyenne"],
    ["dash_text_all_time_earned", "Earned in total", "Insgesamt verdient", "Gain total"],

    // History
    ["history_card_earned", "Earnings", "Einnahmen", "Gains"],
    ["history_card_usage", "Produced", "Erzeugt", "Production"],
    ["history_card_consumption", "Consumed", "Verbraucht", "Consommation"],
    ["history_text_produced", "Energy produced", "Erzeugte PV-Energie", "Energie produite"],
    ["history_text_earned_feedin", "Earned with feed-in", "Verdienst durch Einspeisung", "Gain d'injection"],
    ["history_text_earned_self", "Saved via self-consumption", "Ersparnis durch Eigenverbrauch", "Gain d'autoconsommation"],
    ["history_text_earned_total", "Total", "Summe", "Total"],
    ["history_text_fedin", "Fed into the grid", "Ins Netz eingespeist", "Injection vers le réseau"],
    ["history_text_self_consumed", "Self consumed", "Selbst verbraucht", "Autoconsommé"],
    ["history_text_consumption_grid", "Consumption from grid", "Verbrauch aus dem Netz", "Consommation du réseau"],
    ["history_text_consumption_self", "Consumption from PV", "Verbrauch aus PV", "Consommation solaire"],
    ["history_text_consumption_total", "Total consumption", "Gesamtverbrauch", "Consommation totale"],
    ["history_card_graph_production_text", "Production Details", "Zeitverlauf der Erzeugung", "Détail de production"],
    ["history_card_graph_consumption_text", "Consumption Details", "Zeitverlauf des Verbrauchs", "Détail de consommation"],
    ["history_card_autarky", "Autarky", "Autarkie", "Autonomie"],
    ["history_text_autarky", "Achieved autarky", "Erreichte Autarkie", "Autonomie atteinte"],
    ["history_card_high_res_data_text", "Course of the Day", "Tagesverlauf", "Déroulement de la journée"],

    // CSV download
    ["headline_csv", "CSV Download", "CSV-Download", "Export CSV"],
    ["csv_subtitle", "Download .csv reports", "Report-Dateien im .csv-Format herunterladen", "Télécharger les rapports CSV"],
    ["csv_download_button", "Download", "Herunterladen", "Télécharger"],
    ["csv_download_preparing_text", "Preparing download…", "Download wird vorbereitet…", "Préparation du téléchargement…"],
    ["csv_download_failed", "Export failed. Check the selected date.", "Export fehlgeschlagen. Bitte das gewählte Datum prüfen.", "Échec de l'export. Vérifiez la date sélectionnée."],
    ["csv_download_failed_http", "Export failed (HTTP {status}). Check the selected date.", "Export fehlgeschlagen (HTTP {status}). Bitte das gewählte Datum prüfen.", "Échec de l'export (HTTP {status}). Vérifiez la date sélectionnée."],
    ["csv_download_network_error", "Export failed. Check your network connection.", "Export fehlgeschlagen. Bitte die Netzwerkverbindung prüfen.", "Échec de l'export. Vérifiez votre connexion réseau."],
    ["csv_download_no_data", "No data available for the selected range.", "Keine Daten für den gewählten Zeitraum.", "Aucune donnée pour la période sélectionnée."],
    ["csv_label_time_range", "Time range:", "Zeitraum:", "Période:"],
    ["csv_label_resolution", "Resolution:", "Granularität:", "Découpage:"],
    ["csv_range_rad_lbl_day", "A single day", "Ein Tag","Jour"],
    ["csv_range_rad_lbl_month", "A month", "Ein Monat", "Mois"],
    ["csv_range_rad_lbl_year", "A year", "Ein Jahr", "Année"],
    ["csv_range_rad_lbl_all", "All time", "Alles", "Tout"],
    ["csv_res_rad_lbl_day", "Single days", "Einzelne Tage", "Par jour"],
    ["csv_res_rad_lbl_month", "Summed up by months", "Auf Monate summiert", "Par mois"],
    ["csv_res_rad_lbl_year", "Summed up by years", "Auf Jahre summiert", "Par année"],

    // Date selector accessible names
    ["selection_aria_year", "Year", "Jahr", "Année"],
    ["selection_aria_month", "Month", "Monat", "Mois"],
    ["selection_aria_day", "Day", "Tag", "Jour"],
    ["selection_aria_prev", "Previous", "Zurück", "Précédent"],
    ["selection_aria_next", "Next", "Weiter", "Suivant"],
    ["csv_selection_aria_year", "Year", "Jahr", "Année"],
    ["csv_selection_aria_month", "Month", "Monat", "Mois"],
    ["csv_selection_aria_day", "Day", "Tag", "Jour"],

    // Months combo box
    ["cbx_month_1", "January", "Januar", "Janvier"],
    ["cbx_month_2", "February", "Februar", "Février"],
    ["cbx_month_3", "March", "März", "Mars"],
    ["cbx_month_4", "April", "April", "Avril"],
    ["cbx_month_5", "May", "Mai", "Mai"],
    ["cbx_month_6", "June", "Juni", "Juin"],
    ["cbx_month_7", "July", "Juli", "Juillet"],
    ["cbx_month_8", "August", "August", "Août"],
    ["cbx_month_9", "September", "September", "Septembre"],
    ["cbx_month_10", "October", "Oktober", "Octobre"],
    ["cbx_month_11", "November", "November", "Novembre"],
    ["cbx_month_12", "December", "Dezember", "Décembre"],

    // Months combo box
    ["csv_cbx_month_1", "January", "Januar", "Janvier"],
    ["csv_cbx_month_2", "February", "Februar", "Février"],
    ["csv_cbx_month_3", "March", "März", "Mars"],
    ["csv_cbx_month_4", "April", "April", "Avril"],
    ["csv_cbx_month_5", "May", "Mai", "Mai"],
    ["csv_cbx_month_6", "June", "Juni", "Juin"],
    ["csv_cbx_month_7", "July", "Juli", "Juillet"],
    ["csv_cbx_month_8", "August", "August", "Août"],
    ["csv_cbx_month_9", "September", "September", "Septembre"],
    ["csv_cbx_month_10", "October", "Oktober", "Octobre"],
    ["csv_cbx_month_11", "November", "November", "Novembre"],
    ["csv_cbx_month_12", "December", "Dezember", "Décembre"],

    // Info
    ["info_no_data", "No data is available for the selected time span.", "Für den gewählten Zeitraum liegen keine Daten vor.", "Aucune donnée disponible pour la période sélectionnée"],
];

let chartStrings = [
    // HTML element ID          English (1)             German (2)  French (3)
    ["chart_produced_w", "Production", "Erzeugung", "Production"],
    ["chart_consumed_w", "Consumption", "Verbrauch", "Consommation"],
    ["chart_fed_in_w", "Feed-in", "Einspeisung", "Injection"],
    ["chart_from_grid", "From grid", "Aus dem Netz", "Consommation du réseau"],
    ["chart_from_pv", "From PV", "Aus PV", "Consommation solaire"],
    ["chart_produced", "Produced", "Erzeugt", "Produite"],
    ["chart_consumed", "Consumed", "Verbraucht", "Consommé"],
    ["chart_fed_in", "Feed-in", "Einspeisung", "Injection"],
    ["chart_self_consumed", "Self consumed", "Eigenverbrauch", "Autoconsommée"],
    ["chart_produced_self_kwh", "Consumed directly", "Direktverbrauch", "Consommé directement"],
    ["chart_produced_grid_kwh", "Feed-in", "Einspeisung", "Injection"],
    ["chart_consumed_pv_kwh", "From PV", "Aus PV", "Consommation solaire"],
    ["chart_consumed_grid_kwh", "From grid", "Netzbezug", "Consommation du réseau"],
    ["chart_total", "Total", "Gesamt", "Total"],
];

let historyStrings = [
    // HTML element ID      English (1)             German (2)    French (3)
    ["daily_data", "By Day", "Nach Tag", "Journalier"],
    ["monthly_data", "By Month", "Nach Monat", "Mensuel"],
    ["yearly_data", "By Year", "Nach Jahr", "Annuel"],
    ["all_time_data", "All Time", "Gesamt", "Global"],
];

const ariaLabelBindings = [
    ["selection_year2", "selection_aria_year"],
    ["selection_month2", "selection_aria_month"],
    ["selection_day2", "selection_aria_day"],
    ["selection_prev", "selection_aria_prev"],
    ["selection_next", "selection_aria_next"],
    ["csv_selection_year2", "csv_selection_aria_year"],
    ["csv_selection_month2", "csv_selection_aria_month"],
    ["csv_selection_day2", "csv_selection_aria_day"],
];

const supportedLanguageIndices = [gLangEn, gLangDe, gLangFr];

function normalizeLanguageIndex(index) {
    const parsed = parseInt(index, 10);
    return supportedLanguageIndices.includes(parsed) ? parsed : gLangEn;
}

function detectBrowserLanguageIndex() {
    const candidates = [];
    if (navigator.languages && navigator.languages.length > 0) {
        candidates.push(...navigator.languages);
    }
    if (navigator.language) {
        candidates.push(navigator.language);
    }
    for (let i = 0; i < candidates.length; ++i) {
        const code = candidates[i].split("-")[0].toLowerCase();
        if (code === "de") {
            return gLangDe;
        }
        if (code === "fr") {
            return gLangFr;
        }
        if (code === "en") {
            return gLangEn;
        }
    }
    return gLangEn;
}

function applyAriaLabels() {
    ariaLabelBindings.forEach(binding => {
        try {
            const control = document.getElementById(binding[0]);
            const label = getTranslationString(binding[1]);
            if (control != null && label != null) {
                control.setAttribute("aria-label", label);
            }
        } catch (error) {
            console.error("Could not localize aria-label for " + binding[0] + ": " + error);
        }
    });
}

function getTranslationString(id) {
    for (let i = 0; i < translations.length; ++i) {
        if (translations[i][0] === id) {
            return translations[i][gCurLang];
        }
    }
    return null;
}

function formatStatsBestYearDate(year) {
    const template = getTranslationString("stats_best_year_in");
    if (template == null) {
        return year;
    }
    return template.replace("%s", year);
}


function restoreLanguage() {
    var lang = localStorage.getItem("lang");
    var index = lang != null ? normalizeLanguageIndex(lang) : detectBrowserLanguageIndex();
    switchLanguageByIndex(index, { refreshViews: false });
}

function switchLanguageToEnglish() {
    switchLanguageByIndex(gLangEn);
}

function switchLanguageToGerman() {
    switchLanguageByIndex(gLangDe);
}

function switchLanguageToFrench() {
    switchLanguageByIndex(gLangFr);
}

function switchLanguageByIndex(index, options) {
    const refreshViews = !(options && options.refreshViews === false);
    index = normalizeLanguageIndex(index);
    gCurLang = index;
    localStorage.setItem("lang", index);
    document.documentElement.lang = getLocale();
    translations.forEach(translation => {
        try {
            const element = document.getElementById(translation[0]);
            if (element != null) {
                element.textContent = translation[index];
            }
        } catch (error) {
            console.error("Could not localize element " + translation[0] + ": " + error);
        }
    });
    applyAriaLabels();
    if (typeof refreshChartsForLocale === "function") {
        refreshChartsForLocale();
    }
    if (refreshViews && typeof refreshLocaleDependentViews === "function") {
        refreshLocaleDependentViews();
    }
}

function getChartString(id) {
    for (i = 0; i < chartStrings.length; ++i)
        if (chartStrings[i][0] == id)
            return chartStrings[i][gCurLang];
    return "...";
}

function getHistoryString(id) {
    for (i = 0; i < historyStrings.length; ++i)
        if (historyStrings[i][0] == id)
            return historyStrings[i][gCurLang];
    return "...";
}


// Number format with 2 decimals
const format2_en = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

// Number format with 0 decimals
const format0_en = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
});

// Number format with 2 decimals
const format2_de = new Intl.NumberFormat('de-DE', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

// Number format with 0 decimals
const format0_de = new Intl.NumberFormat('de-DE', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
});

// Number format with 2 decimals
const format2_fr = new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

// Number format with 0 decimals
const format0_fr = new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
});

function getUiString(id) {
    for (let i = 0; i < translations.length; ++i) {
        if (translations[i][0] === id) {
            return translations[i][gCurLang];
        }
    }
    return "";
}

function formatUiString(id, replacements) {
    let text = getUiString(id);
    if (!text) {
        return "";
    }
    if (replacements) {
        for (const key in replacements) {
            text = text.split("{" + key + "}").join(String(replacements[key]));
        }
    }
    return text;
}

const format1_en = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
});
const format1_de = new Intl.NumberFormat('de-DE', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
});
const format1_fr = new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
});

function numFormat1(number) {
    if (!Number.isFinite(number)) {
        return "—";
    }
    if (gCurLang == gLangDe) {
        return format1_de.format(number);
    }
    if (gCurLang == gLangFr) {
        return format1_fr.format(number);
    }
    return format1_en.format(number);
}

function numFormat(number, digits) {
    if (!Number.isFinite(number)) {
        return "—";
    }
    if (digits == 1) {
        return numFormat1(number);
    }
    if (digits == 2) {
        if (gCurLang == gLangDe)
            return format2_de.format(number);
        else if (gCurLang == gLangFr)
            return format2_fr.format(number);
        else
            return format2_en.format(number);
    }
    else {
        if (gCurLang == gLangDe)
            return format0_de.format(number);
        else if (gCurLang == gLangFr)
            return format0_fr.format(number);
        else
            return format0_en.format(number);
    }
}


let monthNames = [
    // English (1), German (2), French (3)
    ["January", "Januar", "Janvier"],
    ["February", "Februar", "Février"],
    ["March", "März", "Mars"],
    ["April", "April", "Avril"],
    ["May", "Mai", "Mai"],
    ["June", "Juni", "Juin"],
    ["July", "Juli", "Juillet"],
    ["August", "August", "Août"],
    ["September", "September", "Septembre"],
    ["October", "Oktober", "Octobre"],
    ["November", "November", "Novembre"],
    ["December", "Dezember", "Décembre"],
];

function getMonthName(index) {
    return monthNames[index][gCurLang - 1];
}

function getLocale() {
    return gCurLang == gLangDe ? "de" : (gCurLang == gLangFr ? "fr" : "en");
}

function getTimeLocaleTag() {
    return gCurLang == gLangDe ? "de-DE" : (gCurLang == gLangFr ? "fr-FR" : "en-US");
}

function getUnitDays() {
    return gCurLang == gLangDe ? "Tage" : (gCurLang == gLangFr ? "jours" : "days");
}

function prettyPrintDateString(date) {
    var d = new Date(date)
    let localeDate = d.toLocaleString(getLocale(), {
        weekday: "long",
        day: "numeric",
        year: "numeric",
        month: "long",
    });
    return localeDate;
}

function prettyPrintDateStringWithoutDay(date) {
    var d = new Date(date)
    let localeDate = d.toLocaleString(getLocale(), {
        year: "numeric",
        month: "long",
    });
    return localeDate;
}