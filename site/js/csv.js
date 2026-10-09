function setCsvDownloadUi(state, options) {
    const preparing = document.getElementById("csv_download_preparing");
    const errorRow = document.getElementById("row_csv_download_error");
    const errorText = document.getElementById("csv_download_error");
    if (preparing) {
        preparing.style.display = state === "preparing" ? "block" : "none";
    }
    if (errorRow && errorText) {
        if (state === "error") {
            errorRow.style.display = "block";
            errorText.textContent = options && options.message ? options.message : getUiString("csv_download_failed");
        } else {
            errorRow.style.display = "none";
            errorText.textContent = "";
        }
    }
}

function buildCsvDownloadErrorMessage(status) {
    if (status === 0) {
        return getUiString("csv_download_network_error");
    }
    if (status >= 200 && status < 300) {
        return getUiString("csv_download_failed");
    }
    return formatUiString("csv_download_failed_http", { status: String(status) });
}

function csvRangeNeedsYear() {
    return document.getElementById("csv_range_rad_year").checked === true
        || document.getElementById("csv_range_rad_month").checked === true
        || document.getElementById("csv_range_rad_day").checked === true;
}

function validateCsvDateSelection() {
    if (document.getElementById("csv_range_rad_all").checked === true) {
        return true;
    }
    const year = document.getElementById("csv_selection_year2").value.toString();
    if (csvRangeNeedsYear() && year === "") {
        setCsvDownloadUi("error", { message: getUiString("csv_download_no_data") });
        return false;
    }
    return true;
}

// Opens a link to download a .csv file from the server
function downloadCsv() {
    setCsvDownloadUi("idle");
    if (!validateCsvDateSelection()) {
        return;
    }
    setCsvDownloadUi("preparing");

    let table = "days";
    if (document.getElementById("csv_res_rad_month").checked == true)
        table = "months";
    else if (document.getElementById("csv_res_rad_year").checked == true)
        table = "years";

    let year = document.getElementById('csv_selection_year2').value.toString();
    let month = padStr(document.getElementById('csv_selection_month2').value.toString());
    let day = padStr(document.getElementById('csv_selection_day2').value.toString());

    let date = "";
    if (document.getElementById("csv_range_rad_all").checked == true)
        date = "";
    else if (document.getElementById("csv_range_rad_year").checked == true)
        date = year;
    else if (document.getElementById("csv_range_rad_month").checked == true)
        date = year + "-" + month;
    else if (document.getElementById("csv_range_rad_day").checked == true)
        date = year + "-" + month + "-" + day;

    if (date.length > 0 && !/^[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$/.test(date)) {
        setCsvDownloadUi("error", { message: getUiString("csv_download_no_data") });
        return;
    }

    let url = gBaseUrl + "csv?table=" + table;
    if (date.length > 0)
        url += "&date=" + date;

    console.log("Executing CSV query: " + url);
    fetch(url).then(async function (response) {
        const contentType = response.headers.get("content-type") || "";
        let data = null;
        if (contentType.includes("json")) {
            data = await response.json();
        } else if (!response.ok) {
            const text = await response.text();
            try {
                data = JSON.parse(text);
            } catch (parseError) {
                data = null;
            }
        }
        if (!response.ok || contentType.includes("json")) {
            setCsvDownloadUi("error", {
                message: buildCsvDownloadErrorMessage(response.status),
            });
            return;
        }
        const blob = await response.blob();
        let fileName = "export.csv";
        const disposition = response.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename=\"?([^\";]+)\"?/i);
        if (match) {
            fileName = match[1];
        }
        const link = document.createElement("a");
        const objectUrl = URL.createObjectURL(blob);
        link.href = objectUrl;
        link.download = fileName;
        link.click();
        setTimeout(function () {
            URL.revokeObjectURL(objectUrl);
        }, 1000);
        setCsvDownloadUi("idle");
    }).catch(function (error) {
        setCsvDownloadUi("error", {
            message: buildCsvDownloadErrorMessage(0),
        });
        console.warn("CSV download failed", error);
    });
}
