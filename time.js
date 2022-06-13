function localize(time)
{
	var date=new Date(time * 1000);
	return document.write(date.toLocaleDateString() + " " + date.toLocaleTimeString());
}
