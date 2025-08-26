function openTab(tabName) {
    var tabContents = document.getElementsByClassName("tab-content");
    for (var i = 0; i < tabContents.length; i++) {
        tabContents[i].classList.remove("active");
    }

    var tabLinks = document.getElementsByClassName("tab-link");
    for (var i = 0; i < tabLinks.length; i++) {
        tabLinks[i].classList.remove("active");
    }

    document.getElementById(tabName).classList.add("active");
    document.getElementById(tabName + "-tab").classList.add("active");
}

document.addEventListener("DOMContentLoaded", function() {
    openTab('requirements');
});
