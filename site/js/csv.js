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

function buildCsvDownloadErrorMessage(status, data) {
    const statusCode = status > 0 ? status : "—";
    let message = formatUiString("csv_download_failed", { status: statusCode });
    const detail = formatApiErrorMessage(data);
    if (detail) {
        message += " " + detail;
    }
    return message;
}

// Opens a link to download a .csv file from the server
function downloadCsv() {
    setCsvDownloadUi("idle");
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
                message: buildCsvDownloadErrorMessage(response.status, data),
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
        link.href = URL.createObjectURL(blob);
        link.download = fileName;
        link.click();
        URL.revokeObjectURL(link.href);
        setCsvDownloadUi("idle");
    }).catch(function (error) {
        setCsvDownloadUi("error", {
            message: buildCsvDownloadErrorMessage(0, null),
        });
        console.warn("CSV download failed", error);
    });
}
