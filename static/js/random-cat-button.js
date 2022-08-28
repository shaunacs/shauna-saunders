function getRandomCatPic() {
    const myCatPics = ['Frankie1.jpg', 'Frankie2.jpg', 'Gary-side.PNG', 'Gary.jpg'];

    var catPic = myCatPics[Math.floor(Math.random()*myCatPics.length)];
    return catPic;
}


function shuffleCats() {
    document.getElementById("cat-image").src = `../static/img/${getRandomCatPic()}`;
}