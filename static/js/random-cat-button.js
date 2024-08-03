let currentIndex = 0;

function getRandomCatPic() {
    const myCatPics = ['Frankie1.jpg', 'Frankie2.jpg', 'Gary-side.PNG', 'Gary.jpg'];
    

    if (myCatPics.length == 0) {
        console.log('No images available')
        return null
    }

    const catPic = myCatPics[currentIndex];
    currentIndex = (currentIndex + 1) % myCatPics.length;
    
    return catPic;
}


function shuffleCats() {
    document.getElementById("cat-image").src = `../static/img/${getRandomCatPic()}`;
}