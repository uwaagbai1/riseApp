(function($){
	"use strict";

	// Mean Menu
	$('.mean-menu').meanmenu({
		meanScreenWidth: "991"
	});

	// Header Sticky
	$(window).on('scroll',function() {
		if ($(this).scrollTop() > 120){  
			$('.navbar-area').addClass("is-sticky");
		}
		else{
			$('.navbar-area').removeClass("is-sticky");
		}
	});

	// Magnific Popup
	$('.popup-youtube, .popup-vimeo, .popup-gmaps').magnificPopup({
		type: 'iframe',
		mainClass: 'mfp-fade',
		removalDelay: 160,
		preloader: false,
		fixedContentPos: false
	});

	// Upcoming Courses Slides
	$('.upcoming-courses-slides').owlCarousel({
		nav: true,
		loop: true,
		margin: 25,
		dots: false,
		autoplay: true,
		autoplayHoverPause: true,
		navText: [
			"<i class='fa-solid fa-chevron-left'></i>",
			"<i class='fa-solid fa-chevron-right'></i>"
		],
		responsive: {
			0: {
				items: 1
			},
			576: {
				items: 1
			},
			768: {
				items: 2
			},
			992: {
				items: 2
			},
			1200: {
				items: 2
			}
		}
	});

	// Feedback Slides
	$('.feedback-slides').owlCarousel({
		items: 1,
		nav: false,
		loop: true,
		margin: 25,
		dots: true,
		autoplay: true,
		autoplayHoverPause: true,
		navText: [
			"<i class='fa-solid fa-chevron-left'></i>",
			"<i class='fa-solid fa-chevron-right'></i>"
		]
	});
	$('.feedback-slides2').owlCarousel({
		items: 1,
		nav: true,
		loop: true,
		margin: 25,
		dots: false,
		autoplay: true,
		autoplayHoverPause: true,
		navText: [
			"<i class='fa-solid fa-arrow-left'></i>",
			"<i class='fa-solid fa-arrow-right'></i>"
		]
	});

	// Testimonials Slides
	$('.testimonials-slides').owlCarousel({
		nav: false,
		loop: true,
		margin: 25,
		dots: true,
		autoplay: true,
		autoplayHoverPause: true,
		navText: [
			"<i class='fa-solid fa-chevron-left'></i>",
			"<i class='fa-solid fa-chevron-right'></i>"
		],
		responsive: {
			0: {
				items: 1
			},
			576: {
				items: 2
			},
			768: {
				items: 2
			},
			992: {
				items: 3
			},
			1200: {
				items: 3
			},
			1600: {
				items: 4
			}
		}
	});

	// Partners Slides
	$('.partners-slides').owlCarousel({
		nav: false,
		loop: true,
		margin: 25,
		dots: false,
		autoplay: true,
		autoplayHoverPause: true,
		navText: [
			"<i class='fa-solid fa-chevron-left'></i>",
			"<i class='fa-solid fa-chevron-right'></i>"
		],
		responsive: {
			0: {
				items: 2
			},
			576: {
				items: 4
			},
			768: {
				items: 3
			},
			992: {
				items: 4
			},
			1200: {
				margin: 40,
				items: 4
			},
			1400: {
				margin: 40,
				items: 5
			},
			1600: {
				margin: 50,
				items: 6
			}
		}
	});

	// scrollCue
	scrollCue.init();

	// Password Show/Hide
	$('#togglePassword').on('click', function() {
        let passwordInput = $('#passwordInput');
        let icon = $(this).find('i');
        
        // Toggle the password field type
        if (passwordInput.attr('type') === 'password') {
            passwordInput.attr('type', 'text');
            icon.removeClass('fa-eye-slash').addClass('fa-eye');
        } else {
            passwordInput.attr('type', 'password');
            icon.removeClass('fa-eye').addClass('fa-eye-slash');
        }
    });

	// Features Slides
    try {
        window.addEventListener('DOMContentLoaded', () => {
            const slides = document.querySelectorAll('.features-slides .slide');
            for (let slide of slides) {
                    slide.addEventListener('click', () => {
                    clearActiveClasses();
                    slide.classList.add('active');
                });
            }
            function clearActiveClasses() { 
				slides.forEach((slide) => {
					slide.classList.remove('active');
				});
            }
        });
    } catch {}

	// Go to Top
	$(function(){
		// Scroll Event
		$(window).on('scroll', function(){
			var scrolled = $(window).scrollTop();
			if (scrolled > 600) $('.go-top').addClass('active');
			if (scrolled < 600) $('.go-top').removeClass('active');
		});  
		// Click Event
		$('.go-top').on('click', function() {
			$("html, body").animate({ scrollTop: "0" },  0);
		});
	});

}(jQuery));