$(function(){

    $(".ispublic").bootstrapSwitch();

    var $newsAlert = $("#news-alert");
    var alertKey = $newsAlert.data("news-key") || "__wr_skipNews";

    $newsAlert.on("close.bs.alert", function () {
        setStorage(alertKey, "1");
    });

    if (getStorage(alertKey) === "1") {
      $newsAlert.hide();
    }

    $('#create-modal').on('shown.bs.modal', function () {
        $('#title').select();
    });
});
