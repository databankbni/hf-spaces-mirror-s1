namespace Portfilio_Site.Models // <-- Changed this!
{
    public class ProjectModel
    {
        public int Id { get; set; }
        public string Title { get; set; }
        public string Description { get; set; }
        public string TechStack { get; set; }
        public string GithubLink { get; set; }
        public string? LiveUrl { get; set; }
    }
}